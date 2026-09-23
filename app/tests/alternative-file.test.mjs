// T053: the alternative-file form over a fake document and request. Regions are
// basis points of the original; alignment is stated as unresolved; formats with no
// formal selector are answered whole only.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  FILE_SCHEMA, MESSAGES, createAlternativeFileForm, selectorFrom, selectorKind, selectorText,
} from '../static/alternative-file.mjs';

const RUN = '00000000-0000-4000-8000-00000000d0d1';
const ART = '11111111-1111-5111-8111-111111111111';
const crypto = { randomUUID: () => '00000000-0000-4000-8000-000000000099' };

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map();
    this._text = ''; this.value = ''; this.checked = false; this.files = [];
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
    for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); }
    return found;
  }
}

const document = { createElement: tag => new FakeElement(tag) };
const file = (bytes, type = 'image/png', name = '내 그림.png') => ({ size: bytes.length, type, name,
  arrayBuffer: async () => bytes.buffer });

function formWith(replies) {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options) => { asked.push([path, options]); const reply = replies.shift(); if (reply instanceof Error) throw reply; return reply; };
  return { root, asked, form: createAlternativeFileForm({ root, document, request, crypto }) };
}

const byId = (root, id) => root.findAll(el => el.getAttribute('id') === id)[0];
const button = (root, text) => root.findAll(el => el.tagName === 'BUTTON' && el.textContent === text)[0];

test('selector kinds and fields are validated before sending', () => {
  assert.equal(selectorKind('image/png'), 'image_region');
  assert.equal(selectorKind('application/pdf'), 'page_region');
  assert.equal(selectorKind('application/octet-stream'), null);
  assert.deepEqual(selectorFrom('image_region', { x: '10', y: '20', width: '50', height: '25.5' }),
    { kind: 'image_region', locator: { x: 1000, y: 2000, width: 5000, height: 2550 } });
  assert.throws(() => selectorFrom('image_region', { x: '60', y: '0', width: '50', height: '10' }));
  assert.throws(() => selectorFrom('page_region', { page: '0', x: '0', y: '0', width: '10', height: '10' }));
  assert.throws(() => selectorFrom('structured_path', { pointer: 'a~2' }));
  assert.deepEqual(selectorFrom('time_range', { start: '1.5', end: '3' }), { kind: 'time_range', locator: { start_ms: 1500, end_ms: 3000 } });
  assert.equal(selectorText({ kind: 'page_region', locator: { page: 2, x: 0, y: 0, width: 10000, height: 2500 } }),
    '2쪽 영역 x 0.00%, y 0.00%, 너비 100.00%, 높이 25.00%');
});

test('an image is answered with regions and the alignment is stated as unresolved', async () => {
  const frozen = { coverage: 'partial', selectors: [{}], alignment_note: 'x' };
  const { root, asked, form } = formWith([frozen]);
  form.open(RUN, { artifactId: ART, mediaType: 'image/png' });
  assert.match(root.textContent, /정렬은 "미정"으로 남습니다/);
  for (const [name, value] of [['x', '10'], ['y', '10'], ['width', '20'], ['height', '20']]) byId(root, `alternative-file-${name}`).value = value;
  await button(root, '이 부분 추가').dispatch('click');
  assert.match(root.textContent, /이미지 영역 x 10\.00%/);
  root.findAll(el => el.getAttribute('type') === 'file')[0].files = [file(new Uint8Array([1, 2, 3]))];
  await button(root, '내 버전으로 기록').dispatch('click');
  const [path, options] = asked[0];
  assert.equal(path, `/api/v1/runs/${RUN}/artifacts/${ART}/alternative-files`);
  assert.equal(options.body.schema_version, FILE_SCHEMA);
  assert.equal(options.body.content_b64, 'AQID');
  assert.deepEqual(options.body.selectors, [{ kind: 'image_region', locator: { x: 1000, y: 1000, width: 2000, height: 2000 } }]);
  assert.equal(options.body.reviewed_whole, false);
  assert.match(root.textContent, /정렬은 미정으로 남았습니다/);
});

test('without a region or whole review nothing is sent; formats without selectors are whole only', async () => {
  const { root, asked, form } = formWith([{ coverage: 'whole', selectors: [] }]);
  form.open(RUN, { artifactId: ART, mediaType: 'application/octet-stream' });
  assert.match(root.textContent, new RegExp(MESSAGES.wholeOnly));
  root.findAll(el => el.getAttribute('type') === 'file')[0].files = [file(new Uint8Array([9]), '', 'x.bin')];
  await button(root, '내 버전으로 기록').dispatch('click');
  assert.equal(asked.length, 0);
  byId(root, 'alternative-file-whole').checked = true;
  await button(root, '내 버전으로 기록').dispatch('click');
  assert.equal(asked[0][1].body.reviewed_whole, true);
  assert.equal(asked[0][1].body.media_type, 'application/octet-stream');
  assert.match(root.textContent, /원본 전체에 대한 내 버전으로 기록했습니다/);
});
