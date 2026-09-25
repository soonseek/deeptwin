// T023: the supported work screen's reading panel (source-reading.mjs) and shared
// conversation (chat.mjs createWorkConversation), over a fake document and request.
// The real server and browser path is browser-work-conversation-t023.test.mjs.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CONVERSATION_ERRORS, CONVERSATION_SCHEMAS, conversationStorageKey, createWorkConversation,
} from '../static/chat.mjs';
import { COMMAND_SCHEMA, ERROR_MESSAGES, createSourceReadings, readingSummary } from '../static/source-reading.mjs';

const BASE = `/${'2'.repeat(32)}/`;
const WORK = '00000000-0000-4000-8000-0000000000a1';
const SOURCE = { kind: 'source', id: '00000000-0000-4000-8000-0000000000b1', version: 1, sha256: 'b'.repeat(64) };
const MODEL = { kind: 'work_model', id: '00000000-0000-4000-8000-0000000000c1', version: 1, sha256: 'c'.repeat(64) };

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = '';
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  append(...nodes) { this.children.push(...nodes); }

  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({ preventDefault() {} }); }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }
}

const document = { createElement: tag => new FakeElement(tag) };
const button = (root, text) => root.findAll(el => el.tagName === 'BUTTON' && el.textContent === text)[0];
const flush = () => new Promise(resolve => setImmediate(resolve));

function requester(handlers) {
  const calls = [];
  async function request(path, options = {}) {
    calls.push([path, options]);
    const handler = handlers.shift();
    if (!handler) throw new Error(`unexpected request ${path}`);
    return handler(path, options);
  }
  return { request, calls };
}

let counter = 0;
const crypto = { randomUUID: () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}` };

function fakeStorage() {
  const map = new Map();
  return { getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, String(value)),
    removeItem: key => map.delete(key), map };
}

test('reading summaries say complete, partial with what was not read, or unreadable with why', () => {
  assert.equal(readingSummary(null), '아직 읽지 않음');
  assert.equal(readingSummary({ state: 'complete', reasons: [], kept_characters: 1200, page_count: null }), '전부 읽음 · 1,200자');
  assert.match(readingSummary({ state: 'partial', reasons: ['pages_without_text'], kept_characters: 5, page_count: 2 }),
    /일부만 읽음 · 2쪽 · 5자 — 글자 층이 없는 쪽이 있습니다/);
  assert.match(readingSummary({ state: 'unreadable', reasons: ['unsupported_format'], kept_characters: 0, page_count: null }),
    /^읽을 수 없음 — 이 형식은 읽을 수 없습니다/);
});

test('the reading panel reads one original only on the owner command and keeps it retryable', async () => {
  const root = new FakeElement('section');
  const listing = reading => ({ work_id: WORK, revision: 2, reader_attached: false,
    sources: [{ source_id: SOURCE.id, source_ref: SOURCE, name: '표.pdf', original_state: 'stored', reading }] });
  const { request, calls } = requester([
    () => listing(null),
    () => { throw Object.assign(new Error('x'), { code: 'unavailable', reason: 'reader_unavailable', status: 503 }); },
    () => listing(null),
  ]);
  let changed = 0;
  const panel = createSourceReadings({ root, document, request, crypto, basePath: BASE, workId: () => WORK,
    onChange: () => { changed += 1; } });
  await panel.load();
  assert.equal(calls.length, 1, 'listing never reads anything');
  assert.match(root.textContent, /아직 읽지 않음/);
  assert.match(root.textContent, /PDF·DOCX 읽기 도구가 이 인스턴스에 연결되어 있지 않습니다/);
  await button(root, '내용 읽기').dispatch('click');
  await flush();
  const [path, options] = calls[1];
  assert.equal(path, `${BASE}api/v1/source-readings/${WORK}`);
  assert.deepEqual(options.body, { schema_version: COMMAND_SCHEMA, command_id: options.body.command_id, source_ref: SOURCE });
  assert.match(root.textContent, new RegExp(ERROR_MESSAGES.reader_unavailable.slice(0, 20)));
  assert.ok(button(root, '내용 읽기'), 'the original stays and can be read again');
  assert.equal(changed, 1);
});

test('a reading whose original was deleted reads as metadata only: no excerpt, no read button', async () => {
  const root = new FakeElement('section');
  const reading = { reading_ref: { kind: 'extraction', id: 'r', version: 1, sha256: 'd'.repeat(64) }, source_ref: SOURCE,
    state: 'complete', reasons: [], method: 'utf8-text-v1', kept_characters: 12, page_count: null,
    pages_without_text: null, read_at_utc: 't', text_state: 'deleted' };
  const { request } = requester([() => ({ work_id: WORK, revision: 2, reader_attached: true,
    sources: [{ source_id: SOURCE.id, source_ref: SOURCE, name: '표.txt', original_state: 'deleted', reading }] })]);
  const panel = createSourceReadings({ root, document, request, crypto, basePath: BASE, workId: () => WORK });
  await panel.load();
  assert.match(root.textContent, /전부 읽음 · 12자 — 원본과 함께 읽은 글자도 지웠습니다/);
  assert.equal(root.findAll(el => el.tagName === 'DETAILS').length, 0);
  assert.equal(root.findAll(el => el.tagName === 'BUTTON').length, 0);
  assert.equal(root.findAll(el => el.getAttribute('data-text-state') === 'deleted').length, 1);
});

function conversationView(overrides = {}) {
  return { work_id: WORK, revision: 2, messages: [], proposals: [], ...overrides };
}

test('a conversation message carries the ticked exact references and never approves by words', async () => {
  const root = new FakeElement('section');
  const storage = fakeStorage();
  const message = { message_id: '00000000-0000-4000-8000-0000000000d1', sequence: 1, text: '응', semantic_origin: 'owner_message',
    actor: { kind: 'human', role: 'owner' }, references: [MODEL], work_revision: 2, proposal_id: null };
  const { request, calls } = requester([
    () => conversationView(),
    () => ({ message }),
    () => conversationView({ messages: [message] }),
  ]);
  const chat = createWorkConversation({ root, document, request, crypto, basePath: BASE, storage,
    work: () => ({ work_id: WORK, revision: 2 }), references: () => [{ label: '현재 작업 모델', ref: MODEL }] });
  await chat.load();
  const input = root.findAll(el => el.getAttribute('id') === 'conversation-input')[0];
  input.value = '응';
  await input.dispatch('input');
  assert.equal(JSON.parse(storage.getItem(conversationStorageKey(BASE, WORK))).draft, '응');
  root.findAll(el => el.tagName === 'INPUT' && el.getAttribute('type') === 'checkbox')[0].checked = true;
  await button(root, '메시지 남기기').dispatch('click');
  await flush();
  const body = calls[1][1].body;
  assert.equal(calls[1][0], `${BASE}api/v1/conversations/${WORK}/messages`);
  assert.deepEqual(Object.keys(body).sort(), ['command_id', 'expected_revision', 'references', 'schema_version', 'text']);
  assert.equal(body.schema_version, CONVERSATION_SCHEMAS.message);
  assert.deepEqual(body.references, [MODEL]);
  assert.equal(calls.some(([path]) => path.endsWith('/approvals') || path.endsWith('/proposals')), false);
  assert.equal(storage.getItem(conversationStorageKey(BASE, WORK)), null, 'the sent draft is cleared');
  assert.match(root.textContent, /소유자 메시지/);
});

test('a proposal is approved only by the exact phrase; an ambiguous answer keeps the text and changes nothing', async () => {
  const root = new FakeElement('section');
  const storage = fakeStorage();
  const message = { message_id: '00000000-0000-4000-8000-0000000000d1', sequence: 1, text: '확정하자', semantic_origin: 'owner_message',
    actor: { kind: 'human', role: 'owner' }, references: [MODEL], work_revision: 2, proposal_id: null };
  const proposal = { proposal_id: '00000000-0000-4000-8000-0000000000e1', command_kind: 'work_model.confirm', target_ref: MODEL,
    message_id: message.message_id, state: 'proposed', approval: null, result: null, challenge: null };
  const challenge = { challenge_id: '00000000-0000-4000-8000-0000000000f1', token: 'T'.repeat(43),
    response_text: '작업 모델 확정 승인 ABCD1234', expires_at_ms: 1 };
  let decided = null;
  const { request, calls } = requester([
    () => conversationView(),
    () => ({ message }),
    () => ({ proposal, challenge }),
    () => conversationView({ messages: [message], proposals: [proposal] }),
    () => { throw Object.assign(new Error('x'), { code: 'conflict', reason: 'approval_ambiguous', status: 409 }); },
    () => conversationView({ messages: [message], proposals: [proposal] }),
    () => ({ proposal: { ...proposal, state: 'executed', result: { outcome: 'executed' } } }),
    () => conversationView({ messages: [message], proposals: [{ ...proposal, state: 'executed' }] }),
  ]);
  const chat = createWorkConversation({ root, document, request, crypto, basePath: BASE, storage,
    work: () => ({ work_id: WORK, revision: 2 }), references: () => [{ label: '현재 작업 모델', ref: MODEL }],
    onDecided: value => { decided = value; } });
  await chat.load();
  const input = root.findAll(el => el.getAttribute('id') === 'conversation-input')[0];
  input.value = '확정하자';
  root.findAll(el => el.getAttribute('type') === 'checkbox')[0].checked = true;
  root.findAll(el => el.tagName === 'SELECT')[0].value = 'work_model.confirm';
  await button(root, '메시지 남기기').dispatch('click');
  await flush();
  assert.equal(calls[2][1].body.schema_version, CONVERSATION_SCHEMAS.proposal);
  assert.deepEqual(calls[2][1].body.target_ref, MODEL);
  assert.match(root.textContent, /확인 문구: 작업 모델 확정 승인 ABCD1234/);
  // an ambiguous answer: refused, nothing decided, the typed text stays
  input.value = '응';
  await button(root, '승인 응답으로 보내기').dispatch('click');
  await flush();
  assert.deepEqual(calls[4][1].body.route, 'chat');
  assert.equal(calls[4][1].body.text, '응');
  assert.equal(input.value, '응');
  assert.equal(decided, null);
  assert.match(root.textContent, new RegExp(CONVERSATION_ERRORS.approval_ambiguous.slice(0, 15)));
  // the button answer carries no words
  await button(root, '승인').dispatch('click');
  await flush();
  const approval = calls[6][1].body;
  assert.deepEqual(Object.keys(approval).sort(), ['challenge_id', 'command_id', 'proposal_id', 'route', 'schema_version', 'text', 'token']);
  assert.equal(approval.route, 'button');
  assert.equal(approval.text, null);
  assert.equal(approval.token, challenge.token);
  assert.equal(decided.state, 'executed');
  assert.match(root.textContent, /실행됨/);
  assert.equal(JSON.stringify([...storage.map.values()]).includes(challenge.token), false, 'the token is never stored');
});

test('a message whose answer was lost is resent under its own command id; a reloaded proposal asks for a fresh challenge', async () => {
  const root = new FakeElement('section');
  const storage = fakeStorage();
  const proposal = { proposal_id: '00000000-0000-4000-8000-0000000000e1', command_kind: 'work_model.reject', target_ref: MODEL,
    message_id: '00000000-0000-4000-8000-0000000000d1', state: 'proposed', approval: null, result: null, challenge: null };
  const { request, calls } = requester([
    () => conversationView({ proposals: [proposal] }),
    () => { throw Object.assign(new Error('offline'), { code: 'unavailable' }); },
    () => conversationView({ proposals: [proposal] }),
    () => ({ message: { message_id: '00000000-0000-4000-8000-0000000000d2', sequence: 1, text: '메모', semantic_origin: 'owner_message',
      actor: { kind: 'human', role: 'owner' }, references: [], work_revision: 2, proposal_id: null } }),
    () => conversationView({ proposals: [proposal] }),
  ]);
  const chat = createWorkConversation({ root, document, request, crypto, basePath: BASE, storage,
    work: () => ({ work_id: WORK, revision: 2 }) });
  await chat.load();
  assert.ok(button(root, '확인 문구 다시 받기'), 'no token survives a reload: a fresh challenge is asked for');
  assert.equal(button(root, '승인'), undefined);
  const input = root.findAll(el => el.getAttribute('id') === 'conversation-input')[0];
  input.value = '메모';
  await button(root, '메시지 남기기').dispatch('click');
  await flush();
  assert.equal(input.value, '메모');
  const first = calls[1][1].body.command_id;
  assert.equal(JSON.parse(storage.getItem(conversationStorageKey(BASE, WORK))).pending.command_id, first);
  await button(root, '메시지 남기기').dispatch('click');
  await flush();
  assert.equal(calls[3][1].body.command_id, first, 'the same command id: the server replays, never doubles');
  assert.equal(input.value, '');
});
