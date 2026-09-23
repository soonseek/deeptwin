// T052: the owner's in-place editor over a fake document, request and scheduler.
// Autosave names the revision it edited from; a conflict keeps the owner's text
// and offers reload or a new draft; freezing is explicit and partial by default.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  AUTOSAVE_MS, ERROR_MESSAGES, FREEZE_SCHEMA, MESSAGES, SAVE_SCHEMA, createAlternativeEditor, draftRoutes, isEditable,
} from '../static/alternatives.mjs';

const RUN = '00000000-0000-4000-8000-00000000c0c1';
const ART = '11111111-1111-5111-8111-111111111111';
const DRAFT = '22222222-2222-5222-8222-222222222222';
let counter = 0;
const crypto = { randomUUID: () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}` };

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this._text = '';
    this.value = '';
    this.checked = false;
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  set innerHTML(_value) { throw new Error('markup is never written'); }

  append(...nodes) { this.children.push(...nodes); }

  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }
}

const document = { createElement: tag => new FakeElement(tag) };

function editorWith(replies) {
  const root = new FakeElement('section');
  const asked = [];
  const timers = [];
  const request = async (path, options) => {
    asked.push([path, options]);
    const reply = replies.shift();
    if (reply instanceof Error) throw reply;
    return reply;
  };
  const editor = createAlternativeEditor({ root, document, request, crypto, schedule: (fn, ms) => { timers.push([fn, ms]); return timers.length; } });
  return { root, asked, timers, editor };
}

const textListing = { original: { format: 'text', text: '첫 줄\n', sha256: 'a'.repeat(64) }, drafts: [] };
const saved = (revision, id = DRAFT) => ({ draft_id: id, revision, format: 'text' });
const conflict = () => Object.assign(new Error('x'), { code: 'conflict' });

test('routes and editable formats are strict', () => {
  const routes = draftRoutes('/');
  assert.equal(routes.freeze(RUN, ART, DRAFT), `/api/v1/runs/${RUN}/artifacts/${ART}/drafts/${DRAFT}/freeze`);
  assert.throws(() => routes.list('../x', ART));
  assert.equal(isEditable('text/csv'), true);
  assert.equal(isEditable('application/pdf'), false);
});

test('opening copies the original and autosave names the revision it edited from', async () => {
  const { root, asked, timers, editor } = editorWith([textListing, saved(1), saved(2)]);
  await editor.open(RUN, { artifactId: ART, mediaType: 'text/plain' });
  assert.match(root.textContent, new RegExp(MESSAGES.original));
  assert.match(root.textContent, /이유나 지시를 적지 않아도 됩니다/);
  const area = root.findAll(el => el.tagName === 'TEXTAREA')[0];
  assert.equal(area.value, '첫 줄\n');
  area.value = '고친 줄\n';
  await area.dispatch('input');
  assert.equal(timers.at(-1)[1], AUTOSAVE_MS);
  await timers.at(-1)[0]();
  await Promise.resolve();
  assert.deepEqual(asked[1][1].body, { schema_version: SAVE_SCHEMA, command_id: asked[1][1].body.command_id,
    draft_id: null, expected_revision: 0, format: 'text', text: '고친 줄\n' });
  await editor.save();  // not dirty: nothing sent
  assert.equal(asked.length, 2);
  area.value = '또 고친 줄\n';
  await area.dispatch('input');
  await editor.save();
  assert.equal(asked[2][1].body.draft_id, DRAFT);
  assert.equal(asked[2][1].body.expected_revision, 1);
  assert.match(root.textContent, /저장됨 \(수정본 2\)/);
});

test('a conflict keeps the owner text and offers reload or a new draft', async () => {
  const { root, asked, editor } = editorWith([textListing, saved(1), conflict(), saved(1, '33333333-3333-5333-8333-333333333333')]);
  await editor.open(RUN, { artifactId: ART, mediaType: 'text/plain' });
  const area = root.findAll(el => el.tagName === 'TEXTAREA')[0];
  area.value = 'a\n'; await area.dispatch('input'); await editor.save();
  area.value = 'b\n'; await area.dispatch('input');
  await assert.rejects(editor.save());
  assert.match(root.textContent, new RegExp(ERROR_MESSAGES.conflict));
  assert.equal(editor.content, 'b\n');
  assert.equal(editor.dirty, true);
  const keep = root.findAll(el => el.tagName === 'BUTTON' && el.textContent === '지금 내용을 새 초안으로 저장')[0];
  await keep.dispatch('click');
  assert.equal(asked.at(-1)[1].body.draft_id, null);
  assert.equal(asked.at(-1)[1].body.text, 'b\n');
});

test('a table is edited cell by cell', async () => {
  const listing = { original: { format: 'table', rows: [['이름', '값'], ['가', '1']], sha256: 'a'.repeat(64) }, drafts: [] };
  const { root, asked, editor } = editorWith([listing, { draft_id: DRAFT, revision: 1, format: 'table' }]);
  await editor.open(RUN, { artifactId: ART, mediaType: 'text/csv' });
  const cells = root.findAll(el => el.tagName === 'INPUT' && el.getAttribute('type') === 'text');
  assert.equal(cells.length, 4);
  assert.equal(cells[3].getAttribute('aria-label'), '2행 2열');
  cells[3].value = '10';
  await cells[3].dispatch('input');
  await editor.save();
  assert.deepEqual(asked[1][1].body.rows, [['이름', '값'], ['가', '10']]);
});

test('freezing is explicit, saves first, and is partial unless whole review is ticked', async () => {
  const frozen = { coverage: 'partial', selectors: [{}], unreviewed_scope: 'x' };
  const { root, asked, editor } = editorWith([textListing, saved(1), frozen]);
  await editor.open(RUN, { artifactId: ART, mediaType: 'text/plain' });
  const area = root.findAll(el => el.tagName === 'TEXTAREA')[0];
  area.value = 'x\n'; await area.dispatch('input');
  const whole = root.findAll(el => el.getAttribute('id') === 'alternative-reviewed-whole')[0];
  assert.equal(whole.checked, false);
  await root.findAll(el => el.tagName === 'BUTTON' && el.textContent === '분석용으로 고정')[0].dispatch('click');
  assert.equal(asked[1][1].method, 'POST');  // saved before freezing
  assert.deepEqual(asked[2][1].body, { schema_version: FREEZE_SCHEMA, command_id: asked[2][1].body.command_id,
    expected_revision: 1, reviewed_whole: false });
  assert.match(root.textContent, /바꾼 부분 1곳을 내 근거로 기록했습니다/);
});

test('a saved draft resumes, and an unchanged copy is refused plainly', async () => {
  const listing = { ...textListing, drafts: [{ draft_id: DRAFT, revision: 3 }] };
  const unchanged = Object.assign(new Error('x'), { code: 'invalid_input' });
  const { root, editor } = editorWith([listing, { draft_id: DRAFT, revision: 3, text: '저장된 내용\n' }, unchanged]);
  await editor.open(RUN, { artifactId: ART, mediaType: 'text/plain' });
  assert.match(root.textContent, /수정본 3/);
  assert.equal(root.findAll(el => el.tagName === 'TEXTAREA')[0].value, '저장된 내용\n');
  await assert.rejects(editor.freeze(false));
  assert.match(root.textContent, new RegExp(MESSAGES.unchanged));
});
