// T060: the observed difference and the honest state of explanations, questions and
// change candidates, over a fake document and request.

import test from 'node:test';
import assert from 'node:assert/strict';

import { MESSAGES, PROPOSE_SCHEMA, createInquiryPanel, differenceRoute } from '../static/inquiry.mjs';

const RUN = '00000000-0000-4000-8000-00000000e0e1';
const ART = '11111111-1111-5111-8111-111111111111';
const ALT = '22222222-2222-5222-8222-222222222222';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this._text = ''; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
  addEventListener(type, listener) { this.listeners ??= new Map(); this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  async dispatch(type) { for (const listener of this.listeners?.get(type) ?? []) await listener({}); }
}

const document = { createElement: tag => new FakeElement(tag) };
const value = {
  observations: [{ description: '원본 2–2행이 대안 2–2행으로 바뀌었다.' }], uncertainties: [],
  evidence_scope: ['selector:text_span:0'], unreviewed_scope: 'outside', impact_scope: 'pending_investigation',
  hypotheses: { state: 'not_generated', families: ['alternative_error', 'expert_judgment', 'system'], reason: '생성기가 연결되어 있지 않다.' },
  inquiry: { state: 'not_opened', reason: '전제가 없어 질문하지 않는다.' },
  change_candidates: { state: 'none', reason: '변경 후보를 만들지 않았다.' },
};

test('the route is strict', () => {
  assert.equal(differenceRoute('/', RUN, ART, ALT), `/api/v1/runs/${RUN}/artifacts/${ART}/alternatives/${ALT}/difference`);
  assert.throws(() => differenceRoute('/', RUN, ART, '../x'));
});

test('an unobserved alternative is observed once, then shown with every unknown stated', async () => {
  const asked = [];
  const replies = [Object.assign(new Error('x'), { code: 'not_found' }), value];
  const request = async (path, options) => { asked.push([path, options]); const reply = replies.shift(); if (reply instanceof Error) throw reply; return reply; };
  const root = new FakeElement('section');
  await createInquiryPanel({ root, document, request }).show(RUN, ART, ALT);
  assert.deepEqual(asked.map(([, options]) => options.method ?? 'GET'), ['GET', 'POST']);
  const text = root.textContent;
  assert.match(text, /관측된 차이 1개/);
  assert.match(text, /내가 바꾼 1곳이 근거입니다/);
  assert.match(text, /새로운 조건부 판단: 검토되지 않음/);
  assert.match(text, /생성기가 연결되어 있지 않다/);
  assert.match(text, new RegExp(MESSAGES.noQuiz));
  assert.match(text, /변경 후보를 만들지 않았다/);
  // no input control: nothing asks the owner to answer anything
  assert.equal(root.findAll(el => ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)).length, 0);
});


const DIFF = '33333333-3333-5333-8333-333333333333';
const observed = { ...value, difference_ref: { kind: 'difference', id: DIFF, version: 1, sha256: 'e'.repeat(64) } };
const choiceRef = { kind: 'model_choice', id: '00000000-0000-4000-8000-000000000003', version: 1, sha256: 'c'.repeat(64) };
const proposedSet = { state: 'proposed', hypotheses: [
  { hypothesis_id: 'system-0', family: 'system', claim: '작성 노드가 원자료를 받지 못했다.', conditions: ['인계가 요약뿐일 때'], predictions: ['원자료를 주면 차이가 사라진다'], status: 'proposed' },
  { hypothesis_id: 'expert_judgment-1', family: 'expert_judgment', claim: '소유자는 추정 표기를 유지한다.', conditions: [], predictions: ['다른 추정 항목에서도 같은 수정'], status: 'proposed' },
] };

test('competing explanations are made only on request, through the connection, and stay proposed', async () => {
  const asked = [];
  const replies = [observed, { state: 'not_generated', hypotheses: [] },
    { key_present: true, catalog: { model_ids: ['claude-opus-5'] } },
    { model_choice_ref: choiceRef }, proposedSet, proposedSet];
  const request = async (path, options) => { asked.push([path, options]); const reply = replies.shift(); if (reply instanceof Error) throw reply; return reply; };
  const root = new FakeElement('section');
  const crypto = { randomUUID: () => '00000000-0000-4000-8000-0000000000aa' };
  await createInquiryPanel({ root, document, request, crypto }).show(RUN, ART, ALT);
  assert.equal(asked.length, 3);  // difference, its hypothesis state, the connection; nothing sent
  assert.ok(root.textContent.includes(MESSAGES.transmission));
  const make = root.findAll(el => el.tagName === 'BUTTON' && el.textContent === '경쟁 설명 만들기')[0];
  await make.dispatch('click');
  assert.deepEqual(asked[4], [`/api/v1/differences/${DIFF}/hypotheses`, { method: 'POST', body: {
    schema_version: PROPOSE_SCHEMA, command_id: crypto.randomUUID(), model_choice_ref: choiceRef } }]);
  const text = root.textContent;
  assert.match(text, /시스템 결손\(정보 추출·검색·활용·전달 실패\) · 제안/);
  assert.match(text, /작성 노드가 원자료를 받지 못했다/);
  assert.match(text, /구별할 예측: 원자료를 주면 차이가 사라진다/);
  assert.ok(text.includes(MESSAGES.proposed));
  assert.equal(root.findAll(el => el.tagName === 'BUTTON' && el.textContent === '경쟁 설명 만들기').length, 0);
});
