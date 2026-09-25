// The work-model panel over a fake document and request: drafting is one explicit action
// after the transmission notice, uses the exact model-choice ref, shows the whole draft
// (blocking unknowns marked) and confirms exactly that draft.

import test from 'node:test';
import assert from 'node:assert/strict';

import { CONFIRM_SCHEMA, DRAFT_SCHEMA, ERROR_MESSAGES, MESSAGES, createWorkModel } from '../static/work-model.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; this.value = ''; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  append(...nodes) { this.children.push(...nodes); if (this.tagName === 'SELECT' && !this.value) this.value = nodes[0]?.getAttribute('value') ?? ''; }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}

const document = { createElement: tag => new FakeElement(tag) };
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const button = (root, text) => root.findAll(el => el.tagName === 'BUTTON' && el.textContent === text)[0];
const WORK = '00000000-0000-4000-8000-000000000001';
const crypto = { randomUUID: () => '00000000-0000-4000-8000-0000000000aa' };

function panel(replies, work = { work_id: WORK, revision: 2, sources: 1 }) {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options) => { asked.push([path, options]); const reply = replies.shift(); if (reply instanceof Error) throw reply; return reply; };
  return { root, asked, model: createWorkModel({ root, document, request, crypto, work: () => work }) };
}

const connection = { key_present: true, catalog: { model_ids: ['claude-opus-5'] } };
const choiceRef = { kind: 'model_choice', id: '00000000-0000-4000-8000-000000000003', version: 1, sha256: 'c'.repeat(64) };
const modelRef = { kind: 'work_model', id: '00000000-0000-4000-8000-000000000009', version: 1, sha256: 'd'.repeat(64) };
const draftView = (state = 'unconfirmed', blocking = ['target-quarter']) => ({
  work_model_id: modelRef.id, work_model_ref: modelRef, state, blocking_unknown_ids: blocking,
  work_model: {
    goals: ['분기 보고서 초안을 쓴다'], completion_conditions: ['세 문단이다'],
    deliverables: [{ description: '초안', media_types: ['text/markdown'], min_items: 1, max_items: 1 }],
    authorities: [], risks: [],
    unknowns: [{ unknown_id: 'target-quarter', question: '어느 분기인가?', impact: 'design', status: 'blocking' }],
    suitability: { recommended_shape: 'single_agent', rationale: '범위가 좁다' } },
});

test('drafting is explicit, uses the exact model choice ref and shows the whole draft', async () => {
  const { root, asked, model } = panel([connection, { model_choice_ref: choiceRef }, draftView(), connection]);
  await model.load();
  assert.equal(asked.length, 1);  // loading reads the connection only; nothing is sent
  assert.match(root.textContent, new RegExp(MESSAGES.transmission.slice(0, 20)));
  await button(root, '작업 모델 만들기').dispatch('click');
  await flush();
  assert.deepEqual(asked[1], ['/api/v1/connections/claude/model-choice', { method: 'POST', body: { model_id: 'claude-opus-5' } }]);
  assert.deepEqual(asked[2], ['/api/v1/work-models', { method: 'POST', body: {
    schema_version: DRAFT_SCHEMA, command_id: crypto.randomUUID(), work_id: WORK, revision: 2, model_choice_ref: choiceRef } }]);
  for (const text of ['분기 보고서 초안을 쓴다', '세 문단이다', '어느 분기인가? · 막힘', '에이전트 하나', MESSAGES.blocking]) {
    assert.match(root.textContent, new RegExp(text.replace(/[?]/g, '\\?')));
  }
});

test('the owner confirms exactly the draft shown', async () => {
  const { root, asked, model } = panel([connection, { model_choice_ref: choiceRef }, draftView(), connection,
    draftView('confirmed'), connection]);
  await model.load();
  await button(root, '작업 모델 만들기').dispatch('click');
  await flush();
  await button(root, '이 작업 모델 수락').dispatch('click');
  await flush();
  assert.deepEqual(asked[4], [`/api/v1/work-models/${modelRef.id}/confirm`, { method: 'POST', body: {
    schema_version: CONFIRM_SCHEMA, command_id: crypto.randomUUID(), work_model_ref: modelRef, decision: 'accepted' } }]);
  assert.match(root.textContent, new RegExp(MESSAGES.confirmed));
  assert.equal(button(root, '이 작업 모델 수락'), undefined);
});

test('no sources, no connection and refusals are said plainly and nothing is sent', async () => {
  const bare = panel([], { work_id: WORK, revision: 1, sources: 0 });
  await bare.model.load();
  assert.equal(bare.asked.length, 0);
  assert.match(bare.root.textContent, new RegExp(MESSAGES.noSources));
  const unconnected = panel([{ key_present: false, catalog: null }]);
  await unconnected.model.load();
  assert.match(unconnected.root.textContent, new RegExp(MESSAGES.noConnection.slice(0, 15)));
  assert.equal(button(unconnected.root, '작업 모델 만들기'), undefined);
  const refused = panel([connection, { model_choice_ref: choiceRef }, Object.assign(new Error('x'), { code: 'model_output_invalid' }), connection]);
  await refused.model.load();
  await button(refused.root, '작업 모델 만들기').dispatch('click');
  await flush();
  assert.match(refused.root.textContent, new RegExp(ERROR_MESSAGES.model_output_invalid.slice(0, 20)));
});
