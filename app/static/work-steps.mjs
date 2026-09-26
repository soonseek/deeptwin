// UI phase 5 (docs/ui/2026-09-26-product-ux-redesign.md §5.1, experience.md §3 UX-D01/UX-D06): the
// work page as one stepped surface. ① 설명·자료 → ② 업무 이해 → ③ 환경 제안 → ④ 준비·시작.
//
// - A step is *reached* when the server holds what it is about (a saved work, a work model, a
//   design request of this work, a prepared environment of this work). Only reached steps are
//   shown, plus the one step after the furthest reached one: the NEXT step, whose own module
//   shows the single call to action (UX-D06: `업무 이해하기` → `환경 제안받기` → `이 설계로 준비` →
//   `업무 시작`) or, when it cannot run, why in one sentence (the raw server reason stays in
//   "기술 정보"). Steps beyond it are not drawn at all — no wall of disabled explanations.
// - A *complete* step folds to a one-line summary ("자료 3개 · 전부 읽음 2, 일부 1") that the owner
//   can open again. The fold is decided once, when the page's first reads have settled (a step
//   the owner just finished stays open in front of them); after that only the owner's own
//   "펼치기"/"접기" changes it.
// The pure half (`stepStates`, the summaries) takes plain facts; the DOM half renders each
// step's header into its mount and hides or folds its body. All text goes through textContent.

import { el, statusChip } from './ui-parts.mjs';

export const STEPS = Object.freeze([
  Object.freeze({ id: 'describe', number: 1, title: '설명·자료' }),
  Object.freeze({ id: 'understand', number: 2, title: '업무 이해' }),
  Object.freeze({ id: 'design', number: 3, title: '환경 제안' }),
  Object.freeze({ id: 'start', number: 4, title: '준비·시작' }),
]);
// the call to action each step leads with (UX-D06)
export const STEP_ACTIONS = Object.freeze({
  describe: '이 인스턴스에 저장', understand: '업무 이해하기', design: '환경 제안받기', start: '업무 시작',
});
export const STATE_TEXT = Object.freeze({
  complete: ['완료', 'ok'], current: ['진행 중', 'info'], next: ['다음 단계', 'warn'],
});

function fail(message) {
  throw new Error(message);
}

const count = value => (Number.isSafeInteger(value) && value > 0 ? value : 0);

// what each step is, from plain facts:
//   describe:   { saved, dirty, revision, sources, readings: { complete, partial, unreadable, notRead } }
//   understand: { state: null | 'unconfirmed' | 'confirmed' | 'rejected', revision, goals, deliverables, blocking }
//   design:     { requests, presented, prepared }
//   start:      { environments, runs }
export function stepStates(facts = {}) {
  const describe = facts.describe ?? {};
  const understand = facts.understand ?? {};
  const design = facts.design ?? {};
  const start = facts.start ?? {};
  const modelState = understand.state ?? null;
  const reached = {
    describe: true,
    understand: modelState !== null,
    design: count(design.requests) > 0,
    start: count(start.environments) > 0,
  };
  // ① is done once the owner has moved past it (understanding, or a design made for this work)
  const complete = {
    describe: Boolean(describe.saved) && !describe.dirty && (reached.understand || reached.design || reached.start),
    understand: modelState === 'confirmed' && (!Number.isSafeInteger(understand.revision)
      || !Number.isSafeInteger(describe.revision) || understand.revision === describe.revision),
    design: count(start.environments) > 0,
    start: count(start.runs) > 0,
  };
  let furthest = 0;
  STEPS.forEach((step, index) => { if (reached[step.id]) furthest = index; });
  const next = STEPS[furthest + 1]?.id ?? null;
  return Object.freeze(STEPS.map(step => {
    const state = complete[step.id] ? 'complete' : reached[step.id] ? 'current' : step.id === next ? 'next' : 'hidden';
    return Object.freeze({ ...step, reached: reached[step.id], complete: complete[step.id], next: step.id === next,
      visible: state !== 'hidden', state, summary: stepSummary(step.id, facts) });
  }));
}

// "자료 3개 · 전부 읽음 2, 일부 1" — the readings in the owner's words (source-reading.mjs labels)
export function readingsText(readings = {}) {
  const parts = [['전부 읽음', readings.complete], ['일부', readings.partial], ['읽을 수 없음', readings.unreadable],
    ['읽지 않음', readings.notRead]].filter(([, value]) => count(value) > 0).map(([label, value]) => `${label} ${value}`);
  return parts.join(', ');
}

export function stepSummary(id, facts = {}) {
  if (id === 'describe') {
    const value = facts.describe ?? {};
    const saved = value.saved ? `수정본 ${value.revision ?? '?'} 저장됨${value.dirty ? ' (저장하지 않은 변경 있음)' : ''}` : '아직 저장하지 않음';
    const sources = count(value.sources) ? `자료 ${value.sources}개` : '자료 없음';
    const readings = readingsText(value.readings);
    return [saved, readings ? `${sources} · ${readings}` : sources].join(' · ');
  }
  if (id === 'understand') {
    const value = facts.understand ?? {};
    if (!value.state) return '아직 업무를 이해하지 않았습니다';
    const state = { confirmed: '작업 모델 수락함', unconfirmed: '작업 모델 초안 · 수락 대기', rejected: '작업 모델 거절함' }[value.state] ?? value.state;
    const parts = [state];
    if (Number.isSafeInteger(value.revision)) parts.push(`수정본 ${value.revision} 기준`);
    if (count(value.goals)) parts.push(`목표 ${value.goals}개`);
    if (count(value.deliverables)) parts.push(`산출물 ${value.deliverables}개`);
    if (count(value.blocking)) parts.push(`막힌 미결 ${value.blocking}개`);
    return parts.join(' · ');
  }
  if (id === 'design') {
    const value = facts.design ?? {};
    const parts = [`설계 요청 ${count(value.requests)}개`];
    if (Number.isSafeInteger(value.presented)) parts.push(`제시된 후보 ${value.presented}개`);
    const prepared = count(facts.start?.environments);
    if (prepared) parts.push(`준비된 환경 ${prepared}개`);
    return parts.join(' · ');
  }
  const value = facts.start ?? {};
  return [`준비된 환경 ${count(value.environments)}개`, `시작한 실행 ${count(value.runs)}개`].join(' · ');
}

// the DOM half: `roots` maps each step id to its mount ({ root, body }); `update(facts)` redraws
export function createWorkSteps({ document, roots, onToggle = () => {} } = {}) {
  if (typeof document?.createElement !== 'function') fail('a document is required');
  for (const step of STEPS) {
    if (typeof roots?.[step.id]?.root?.replaceChildren !== 'function' || typeof roots[step.id]?.body !== 'object') {
      fail(`the steps need the ${step.id} mount`);
    }
  }
  const heads = {};
  const collapsed = {};   // step id -> true/false once decided
  let settled = false;
  let states = stepStates({});

  for (const step of STEPS) {
    const { root, body } = roots[step.id];
    const head = el(document, 'div', { className: 'work-step-head' });
    heads[step.id] = head;
    root.insertBefore?.(head, root.firstChild ?? null) ?? root.append(head);
    if (!body.id) body.setAttribute?.('id', `step-${step.id}-body`);
  }

  function toggle(id) {
    collapsed[id] = !collapsed[id];
    render();
    onToggle(id, collapsed[id]);
  }

  function renderHead(state) {
    const { root, body } = roots[state.id];
    const head = heads[state.id];
    const [label, tone] = STATE_TEXT[state.state] ?? ['', 'neutral'];
    const folded = state.state !== 'next' && collapsed[state.id] === true;
    const title = el(document, 'h2', { className: 'step-title', attrs: { id: `step-${state.id}-title` } }, [
      el(document, 'span', { className: 'step-number', text: String(state.number), attrs: { 'aria-hidden': 'true' } }),
      el(document, 'span', { className: 'visually-hidden', text: `${state.number}단계 ` }),
      el(document, 'span', { className: 'step-name', text: state.title }),
    ]);
    const parts = [title, statusChip(document, { tone, label })];
    if (state.state !== 'next') {
      const button = el(document, 'button', { className: 'btn btn-quiet step-toggle', text: folded ? '펼치기' : '접기',
        attrs: { type: 'button', 'aria-expanded': folded ? 'false' : 'true', 'aria-controls': body.id || `step-${state.id}-body`,
          'aria-label': `${state.title} ${folded ? '펼치기' : '접기'}` } });
      button.addEventListener('click', () => toggle(state.id));
      parts.push(button);
    }
    head.replaceChildren(...parts);
    if (state.state === 'next' && STEP_ACTIONS[state.id]) {
      head.append(el(document, 'p', { className: 'step-next-action' }, [
        el(document, 'span', { className: 'step-next-label', text: '다음 할 일' }),
        el(document, 'span', { className: 'step-next-name', text: STEP_ACTIONS[state.id] })]));
    }
    if (folded || state.complete) {
      head.append(el(document, 'p', { className: 'step-summary', text: state.summary }));
    }
    root.hidden = !state.visible;
    root.dataset.state = state.state;
    root.dataset.folded = folded ? 'true' : 'false';
    body.hidden = folded;
  }

  function render() {
    for (const state of states) renderHead(state);
  }

  function update(facts) {
    states = stepStates(facts);
    if (settled) {
      // a step seen for the first time folds only if it is already complete
      for (const state of states) if (state.visible && collapsed[state.id] === undefined) collapsed[state.id] = false;
    }
    render();
    return states;
  }

  // the first reads are in: complete steps fold, the others stay open
  function settle(facts) {
    states = stepStates(facts);
    if (!settled) {
      for (const state of states) collapsed[state.id] = state.complete && state.state !== 'next';
      settled = true;
    }
    render();
    return states;
  }

  function open(id) {
    if (!Object.hasOwn(roots, id)) return false;
    collapsed[id] = false;
    render();
    return true;
  }

  return Object.freeze({ update, settle, open, toggle, get states() { return states; }, get settled() { return settled; } });
}
