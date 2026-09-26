// T060: the observed difference and the honest state of explanations, questions and
// change candidates, over a fake document and request.

import test from 'node:test';
import assert from 'node:assert/strict';

import { INQUIRY_SCHEMAS, MESSAGES, PROPOSE_SCHEMA, createInquiryPanel, differenceRoute } from '../static/inquiry.mjs';

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

// --- the owner's inquiry (T060): opened only by the owner, every question optional ---

const openedState = {
  state: 'open', frozen_at: '2026-09-26T00:00:00.000000Z', revision: 1, unanswered_count: 2,
  questions: [
    { question_id: 'q1', text: '이 예측이 실제 업무에서 맞습니까? “원자료를 주면 차이가 사라진다”', origin: 'hypothesis_prediction',
      hypothesis_ids: ['system-0'], if_yes: 'system-0 설명을 뒷받침합니다.', if_no: 'system-0 설명을 약화합니다.' },
    { question_id: 'q2', text: '다른 보고서에서도 이렇게 고치십니까?', origin: 'model_proposal', hypothesis_ids: ['expert_judgment-1'],
      if_yes: null, if_no: null },
  ],
  answers: [], evidence: [], judgments: [], change_candidates: [], no_change_conclusions: [],
  hypotheses: proposedSet.hypotheses, spli: { state: 'not_opened', reason: '렌즈 기반 질문은 열리지 않았습니다.' },
};
const EVIDENCE_ID = '44444444-4444-5444-8444-444444444444';

function routed(routes) {
  const asked = [];
  const request = async (path, options) => {
    asked.push([path, options]);
    const key = `${options.method ?? 'GET'} ${path.replace(`/api/v1/inquiries/${DIFF}`, 'INQ')}`;
    const handler = routes[key];
    if (handler === undefined) throw Object.assign(new Error(key), { code: 'not_found' });
    return typeof handler === 'function' ? handler(options) : handler;
  };
  return { asked, request };
}

const buttons = (root, text) => root.findAll(el => el.tagName === 'BUTTON' && el.textContent === text);
const byId = (root, id) => root.findAll(el => el.getAttribute('id') === id)[0];

test('the inquiry opens only on the owner\'s click, with no model unless one is picked', async () => {
  let state = { state: 'not_opened', can_open: true, questions: [], answers: [], evidence: [], judgments: [],
    hypotheses: proposedSet.hypotheses, change_candidates: [] };
  const { asked, request } = routed({
    [`GET /api/v1/runs/${RUN}/artifacts/${ART}/alternatives/${ALT}/difference`]: observed,
    [`GET /api/v1/differences/${DIFF}/hypotheses`]: proposedSet,
    'GET /api/v1/connections/claude': { key_present: true, catalog: { model_ids: ['model-a'] } },
    'GET INQ': () => state,
    'POST INQ': () => { state = openedState; return state; },
  });
  const root = new FakeElement('section');
  const crypto = { randomUUID: () => '00000000-0000-4000-8000-0000000000bb' };
  await createInquiryPanel({ root, document, request, crypto }).show(RUN, ART, ALT);
  assert.equal(asked.filter(([, options]) => options.method === 'POST').length, 0);  // nothing opens by itself
  assert.ok(root.textContent.includes(MESSAGES.inquiryClosed));
  await buttons(root, '탐구 열기')[0].dispatch('click');
  const posted = asked.filter(([, options]) => options.method === 'POST');
  assert.deepEqual(posted, [[`/api/v1/inquiries/${DIFF}`, { method: 'POST', body: {
    schema_version: INQUIRY_SCHEMAS.open, command_id: crypto.randomUUID(), model_choice_ref: null } }]]);
  const text = root.textContent;
  assert.ok(text.includes(MESSAGES.optional));
  assert.match(text, /q1 · 설명의 예측에서/);
  assert.match(text, /q2 · 모델 제안 질문/);
  assert.match(text, /그렇다면: system-0 설명을 뒷받침합니다/);
  assert.equal(root.findAll(el => el.getAttribute('data-answer-state') === 'unanswered').length, 2);
  assert.match(text, new RegExp(MESSAGES.noCandidate));
});

test('answers come only from what the owner typed; a skip sends no text; judgments cite evidence', async () => {
  let state = openedState;
  const posts = [];
  const { request } = routed({
    [`GET /api/v1/runs/${RUN}/artifacts/${ART}/alternatives/${ALT}/difference`]: observed,
    [`GET /api/v1/differences/${DIFF}/hypotheses`]: proposedSet,
    'GET INQ': () => state,
    'POST INQ/answers': options => { posts.push(options.body); return state; },
    'POST INQ/evidence': options => {
      posts.push(options.body);
      state = { ...state, evidence: [{ evidence_id: EVIDENCE_ID, text: options.body.text, sources: options.body.sources }] };
      return state;
    },
    'POST INQ/judgments': options => {
      posts.push(options.body);
      state = { ...state, hypotheses: state.hypotheses.map(item => item.hypothesis_id === 'expert_judgment-1' ? { ...item, status: 'confirmed' } : { ...item, status: 'refuted' }),
        change_candidates: [{ candidate_id: 'c1', kind: 'learn', claim: '소유자는 추정 표기를 유지한다.', evidence_refs: [{}],
          leak_check: 'passed', next_step: '제안만 남기고 적용하지 않습니다.', state: 'proposed', applied: false }] };
      return state;
    },
    'GET INQ/audit': { owner_inputs: { answers: 1, skips: 1, evidence: 1, judgments: 1 }, inputs_not_from_owner: 0,
      note: '소유자 입력만 기록합니다.', model_turns: [{ purpose: 'diagnosis_hypotheses', model_id: 'model-a', requested_at: 't0', outcome: { state: 'completed' } }],
      timeline: [{ at: 't1', actor: 'owner', kind: 'answer', question_id: 'q1' }] },
  });
  const root = new FakeElement('section');
  let n = 0;
  const crypto = { randomUUID: () => `00000000-0000-4000-8000-${String(++n).padStart(12, '0')}` };
  await createInquiryPanel({ root, document, request, crypto }).show(RUN, ART, ALT);
  // an empty answer box never produces an answer
  await buttons(root, 'q1 답 저장')[0].dispatch('click');
  assert.equal(posts.length, 0);
  byId(root, 'inquiry-answer-q1').value = '네, 원자료를 주니 사라졌습니다.';
  await buttons(root, 'q1 답 저장')[0].dispatch('click');
  await buttons(root, 'q2 건너뛰기')[0].dispatch('click');
  assert.deepEqual(posts.map(({ question_id, action, text }) => [question_id, action, text]), [
    ['q1', 'answer', '네, 원자료를 주니 사라졌습니다.'], ['q2', 'skip', null]]);
  byId(root, 'inquiry-evidence-text').value = '지난 보고서 세 건도 같은 수정';
  byId(root, 'inquiry-evidence-sources').value = '보고서 7월\n\n보고서 8월\n';
  await buttons(root, '근거 추가')[0].dispatch('click');
  assert.deepEqual(posts[2].sources, ['보고서 7월', '보고서 8월']);
  byId(root, 'inquiry-judgment-expert_judgment-1').value = 'confirmed';
  byId(root, `inquiry-judgment-expert_judgment-1-cite-${EVIDENCE_ID}`).checked = true;
  await buttons(root, 'expert_judgment-1 판단 기록')[0].dispatch('click');
  assert.deepEqual(posts[3], { schema_version: INQUIRY_SCHEMAS.judgment, command_id: posts[3].command_id,
    hypothesis_id: 'expert_judgment-1', judgment: 'confirmed', evidence_ids: [EVIDENCE_ID], note: null });
  const text = root.textContent;
  assert.match(text, /학습 변경 제안 · 제안 · 적용되지 않음/);
  assert.ok(text.includes(MESSAGES.candidateNote));
  await buttons(root, '감사 상세 보기')[0].dispatch('click');
  assert.match(root.textContent, /소유자 입력: 답 1 · 건너뜀 1 · 근거 1 · 판단 1/);
  assert.match(root.textContent, /소유자 입력이 아닌 사람 답: 0/);
  assert.match(root.textContent, /경쟁 설명 · model-a · t0 · 결과 completed/);
});
