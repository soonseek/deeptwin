// UI phase 5 (docs/ui/2026-09-26-product-ux-redesign.md §5.1): the work page's steps. Only reached
// steps and the one next step are drawn; a complete step folds to one line once the first reads
// settle, and the owner's own toggle wins afterwards. Pure rules and a fake document.

import test from 'node:test';
import assert from 'node:assert/strict';

import { STEPS, STEP_ACTIONS, createWorkSteps, readingsText, stepStates, stepSummary } from '../static/work-steps.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; this.hidden = false; this.id = ''; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  get firstChild() { return this.children[0] ?? null; }
  append(...nodes) { this.children.push(...nodes); }
  insertBefore(node, before) { const index = this.children.indexOf(before); if (index < 0) this.children.push(node); else this.children.splice(index, 0, node); return node; }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); if (name === 'id') this.id = String(value); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}
const document = { createElement: tag => new FakeElement(tag) };

const states = facts => Object.fromEntries(stepStates(facts).map(step => [step.id, step.state]));
const saved = { describe: { saved: true, dirty: false, revision: 2, sources: 1, readings: { notRead: 1 } } };

test('a new work shows step ① and the next step ② only, with UX-D06 labels for what comes next', () => {
  assert.deepEqual(STEPS.map(step => step.title), ['설명·자료', '업무 이해', '환경 제안', '준비·시작']);
  assert.deepEqual([STEP_ACTIONS.understand, STEP_ACTIONS.design, STEP_ACTIONS.start], ['업무 이해하기', '환경 제안받기', '업무 시작']);
  assert.deepEqual(states({}), { describe: 'current', understand: 'next', design: 'hidden', start: 'hidden' });
  // saving alone does not complete ①: it is complete once understanding is reached
  assert.deepEqual(states(saved), { describe: 'current', understand: 'next', design: 'hidden', start: 'hidden' });
});

test('each step is reached by what the server holds; the next step follows the furthest one reached', () => {
  const drafted = { ...saved, understand: { state: 'unconfirmed', revision: 2 } };
  assert.deepEqual(states(drafted), { describe: 'complete', understand: 'current', design: 'next', start: 'hidden' });
  const confirmed = { ...saved, understand: { state: 'confirmed', revision: 2 } };
  assert.deepEqual(states(confirmed), { describe: 'complete', understand: 'complete', design: 'next', start: 'hidden' });
  // a model of an older revision is not the understanding of the current one
  const older = { ...saved, describe: { ...saved.describe, revision: 3 }, understand: { state: 'confirmed', revision: 2 } };
  assert.equal(states(older).understand, 'current');
  const designed = { ...confirmed, design: { requests: 1, presented: 3 } };
  assert.deepEqual(states(designed), { describe: 'complete', understand: 'complete', design: 'current', start: 'next' });
  const prepared = { ...designed, start: { environments: 1, runs: 0 } };
  assert.deepEqual(states(prepared), { describe: 'complete', understand: 'complete', design: 'complete', start: 'current' });
  assert.equal(states({ ...prepared, start: { environments: 1, runs: 2 } }).start, 'complete');
  // a design request made without an understanding on this page (a test actor's seed): ② stays
  // undrawn, and ① is done — the owner has moved past it
  assert.deepEqual(states({ ...saved, design: { requests: 1 } }), { describe: 'complete', understand: 'hidden', design: 'current', start: 'next' });
  // an unsaved edit reopens ①
  assert.equal(states({ ...confirmed, describe: { ...saved.describe, dirty: true } }).describe, 'current');
});

test('the one-line summaries say what each step holds', () => {
  assert.equal(readingsText({ complete: 2, partial: 1, notRead: 0 }), '전부 읽음 2, 일부 1');
  assert.equal(stepSummary('describe', { describe: { saved: true, revision: 3, sources: 3, readings: { complete: 2, partial: 1 } } }),
    '수정본 3 저장됨 · 자료 3개 · 전부 읽음 2, 일부 1');
  assert.equal(stepSummary('understand', { understand: { state: 'confirmed', revision: 3, goals: 2, deliverables: 1 } }),
    '작업 모델 수락함 · 수정본 3 기준 · 목표 2개 · 산출물 1개');
  assert.equal(stepSummary('design', { design: { requests: 1, presented: 3 }, start: { environments: 1 } }),
    '설계 요청 1개 · 제시된 후보 3개 · 준비된 환경 1개');
  assert.equal(stepSummary('start', { start: { environments: 1, runs: 2 } }), '준비된 환경 1개 · 시작한 실행 2개');
});

function mounted() {
  const roots = Object.fromEntries(STEPS.map(step => {
    const root = new FakeElement('li');
    const body = new FakeElement('div');
    body.setAttribute('id', `step-${step.id}-body`);
    root.append(body);
    return [step.id, { root, body }];
  }));
  return { roots, steps: createWorkSteps({ document, roots }) };
}
const toggle = root => root.findAll(el => el.tagName === 'BUTTON')[0];

test('complete steps fold once the first reads settle; a step finished on screen stays open; the owner toggles', async () => {
  const { roots, steps } = mounted();
  const confirmed = { ...saved, understand: { state: 'confirmed', revision: 2, goals: 1, deliverables: 1 } };
  steps.update({});
  assert.equal(roots.understand.root.hidden, false);
  assert.equal(roots.design.root.hidden, true);
  assert.equal(toggle(roots.understand.root), undefined, 'the next step has no fold');
  assert.match(roots.understand.root.textContent, /다음 할 일업무 이해하기/);
  steps.settle(confirmed);
  assert.equal(roots.describe.root.dataset.folded, 'true');
  assert.equal(roots.describe.body.hidden, true);
  assert.equal(roots.understand.root.dataset.folded, 'true');
  assert.match(roots.understand.root.textContent, /작업 모델 수락함/);
  assert.equal(roots.design.root.dataset.state, 'next');
  assert.match(roots.design.root.textContent, /환경 제안받기/);
  const button = toggle(roots.understand.root);
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  assert.equal(button.getAttribute('aria-controls'), 'step-understand-body');
  await button.dispatch('click');
  assert.equal(roots.understand.body.hidden, false);
  assert.equal(toggle(roots.understand.root).getAttribute('aria-expanded'), 'true');
  // a step completed after settling stays open in front of the owner
  steps.update({ ...confirmed, design: { requests: 1 }, start: { environments: 1 } });
  assert.equal(roots.design.root.dataset.state, 'complete');
  assert.equal(roots.design.root.dataset.folded, 'false');
  assert.equal(roots.start.root.hidden, false);
  assert.throws(() => createWorkSteps({ document, roots: {} }), /mount/);
});
