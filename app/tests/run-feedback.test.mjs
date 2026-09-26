// UI phase 4 (§5.3, §6): the owner's process feedback on a run — run-feedback.mjs (routes, the
// exact command, the lookup by target, the header summary, graph/timeline markers and the
// control) and its place in run-detail.mjs ("이 결과 전체" in the final block, the selected
// attempt in the selection panel). No reason is ever asked for: a mark alone or a memo alone
// saves; saving is explicit; a stale revision is refused and the server's latest shown. Text
// only, never markup. Synthetic test-actor data.

import test from 'node:test';
import assert from 'node:assert/strict';

process.env.TZ = 'Asia/Seoul';

const {
  MEMO_MAX, MESSAGES, createFeedbackControl, feedbackCommand, feedbackFor, feedbackIndex, feedbackRoute,
  feedbackSummary, memoValue, nodeMarkers, runTarget, savedText, stepMarker, stepTarget, targetKey,
} = await import('../static/run-feedback.mjs');
const { createRunDetail } = await import('../static/run-detail.mjs');
const { RUN, sampleTrace } = await import('./helpers/run-trace-sample.mjs');

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.value = '';
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  set innerHTML(_value) { throw new Error('markup is never written'); }

  append(...nodes) { this.children.push(...nodes); }

  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  removeAttribute(name) { this.attributes.delete(name); }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  async dispatch(type, event = {}) {
    for (const listener of this.listeners.get(type) ?? []) await listener({ ...event, preventDefault() {} });
  }

  focus() {}

  scrollIntoView() {}

  hasClass(name) { return (this.getAttribute('class') ?? '').split(/\s+/).includes(name); }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }

  find(predicate) { return this.findAll(predicate)[0] ?? null; }

  querySelectorAll(selector) {
    const [tag, className] = selector.split('.');
    return this.findAll(node => node.tagName === tag.toUpperCase() && node.hasClass(className));
  }
}

const document = { createElement: tag => new FakeElement(tag) };
const tick = () => new Promise(resolve => setImmediate(resolve));
const CMD = n => `00000000-0000-4000-8000-${String(900000 + n).padStart(12, '0')}`;
const STAMP = '2026-09-26T05:10:00.000000Z';

function item(target, revision, { mark = null, memo = null, state = 'set' } = {}) {
  return { feedback_id: `00000000-0000-4000-8000-${String(700 + revision).padStart(12, '0')}`, revision, target,
    state, mark, memo, recorded_at_utc: STAMP, ref: {} };
}

test('the route, the targets and the exact command; a set needs a mark or a memo, never a reason', () => {
  assert.equal(feedbackRoute('/', RUN), `/api/v1/runs/${RUN}/feedback`);
  assert.equal(feedbackRoute(`/${'a'.repeat(32)}/`, RUN), `/${'a'.repeat(32)}/api/v1/runs/${RUN}/feedback`);
  assert.throws(() => feedbackRoute('/x/', RUN));
  assert.throws(() => feedbackRoute('/', 'not-a-run'));
  assert.equal(targetKey(runTarget()), 'run');
  assert.equal(targetKey(stepTarget('publish', 1, 2)), 'step:publish:1:2');
  assert.equal(targetKey(stepTarget('intake', 1)), 'step:intake:1:-');
  for (const bad of [['Publish', 1, 1], ['publish', 0, 1], ['publish', 1, 0], ['../x', 1, null]]) {
    assert.throws(() => stepTarget(...bad), String(bad));
  }
  // a mark alone and a memo alone are each complete
  assert.deepEqual(feedbackCommand({ commandId: CMD(1), target: runTarget(), mark: 'needs_attention' }), {
    schema_version: 'process-feedback-command-v1', command_id: CMD(1), action: 'set', target: { scope: 'run' },
    expected_revision: 0, mark: 'needs_attention', memo: null });
  assert.equal(feedbackCommand({ commandId: CMD(2), target: runTarget(), memo: '메모만' }).memo, '메모만');
  // nothing, a blank memo, an unknown mark or an oversize memo is not a feedback
  assert.throws(() => feedbackCommand({ commandId: CMD(3), target: runTarget() }), /mark or a memo/);
  assert.throws(() => feedbackCommand({ commandId: CMD(3), target: runTarget(), memo: '   \n' }), /mark or a memo/);
  assert.throws(() => feedbackCommand({ commandId: CMD(3), target: runTarget(), mark: 'great' }));
  assert.throws(() => feedbackCommand({ commandId: CMD(3), target: runTarget(), memo: '가'.repeat(MEMO_MAX + 1) }),
    error => error.code === 'too_large');
  assert.equal(feedbackCommand({ commandId: CMD(3), target: runTarget(), memo: '가'.repeat(MEMO_MAX) }).memo.length, MEMO_MAX);
  // a clear names the revision and carries nothing
  assert.deepEqual(feedbackCommand({ commandId: CMD(4), target: stepTarget('publish', 1, 1), action: 'clear',
    expectedRevision: 2 }), { schema_version: 'process-feedback-command-v1', command_id: CMD(4), action: 'clear',
    target: { scope: 'step', node_id: 'publish', visit_no: 1, attempt_no: 1 }, expected_revision: 2, mark: null, memo: null });
  assert.throws(() => feedbackCommand({ commandId: CMD(4), target: runTarget(), action: 'clear', mark: 'ok' }));
  assert.equal(memoValue('  '), null);
  assert.equal(memoValue(' 줄\n'), ' 줄\n');
  assert.match(MESSAGES.hint, /이유를 적지 않아도 됩니다/);
});

test('the lookup, the markers and the header summary count only current feedback', () => {
  const feedback = {
    run: item({ scope: 'run' }, 2, { mark: 'needs_attention' }),
    steps: [
      item(stepTarget('publish', 1, 1), 1, { mark: 'ok', memo: '시도 1은 괜찮음' }),
      item(stepTarget('publish', 1, 2), 3, { mark: 'needs_attention' }),
      item(stepTarget('writer', 1), 1, { memo: '메모만' }),
      item(stepTarget('intake', 1), 2, { state: 'cleared' }),
    ],
  };
  const index = feedbackIndex(feedback);
  assert.equal(feedbackFor(index, runTarget()).item.mark, 'needs_attention');
  assert.equal(feedbackFor(index, runTarget()).revision, 2);
  // a cleared target shows nothing but keeps the revision a change must name
  assert.deepEqual({ ...feedbackFor(index, stepTarget('intake', 1)) }, { item: null, revision: 2 });
  assert.deepEqual({ ...feedbackFor(index, stepTarget('report', 1)) }, { item: null, revision: 0 });
  // one marker per node: 확인 필요 wins over 괜찮음 on the same node
  const markers = nodeMarkers(feedback);
  assert.deepEqual([...markers.entries()].map(([node, marker]) => [node, marker.kind]),
    [['publish', 'needs_attention'], ['writer', 'memo']]);
  assert.equal(markers.get('publish').label, '피드백: 확인 필요');
  assert.equal(stepMarker(index, 'publish', 1, 1).kind, 'ok');
  assert.equal(stepMarker(index, 'intake', 1, null), null);
  const summary = feedbackSummary(feedback);
  assert.equal(summary.text, '결과 전체: 확인 필요 · 확인 필요 1개 단계 · 메모만 1개 단계');
  // each part keeps its own tone: a count of 괜찮음 never reads as a warning
  assert.deepEqual(summary.parts.map(part => part.tone), ['warn', 'warn', 'neutral']);
  assert.deepEqual(feedbackSummary({ run: null, steps: [item(stepTarget('writer', 1), 1, { mark: 'ok' })] }).parts
    .map(part => [part.label, part.tone]), [['괜찮음 1개 단계', 'ok']]);
  assert.equal(summary.tone, 'warn');
  assert.equal(feedbackSummary({ run: null, steps: [] }).any, false);
  assert.equal(savedText(item({ scope: 'run' }, 1), Date.parse('2026-09-26T05:13:00Z')), '저장됨 · 3분 전');
});

test('the control: toggles with aria-pressed, an optional memo, an explicit save and a clear', async () => {
  const saves = [];
  const clears = [];
  let control;
  control = createFeedbackControl({ document, idPrefix: 'feedback-run', now: () => Date.parse('2026-09-26T05:13:00Z'),
    onSave: async value => { saves.push(value); control.show({ heading: '이 결과 전체', item: item({ scope: 'run' }, 1, value) }); },
    onClear: async () => { clears.push(true); control.show({ heading: '이 결과 전체', item: null }); } });
  control.show({ heading: '이 결과 전체' });
  const status = () => control.status.textContent;
  assert.equal(control.root.getAttribute('aria-label'), '이 결과 전체에 대한 피드백');
  assert.match(control.root.textContent, /이유를 적지 않아도 됩니다/);
  assert.equal(status(), MESSAGES.none);
  assert.equal(control.save.disabled, true);
  assert.equal(control.clear.hidden, true);
  // 확인 필요 alone, no memo: saved as it is
  await control.buttons.needs_attention.dispatch('click');
  assert.equal(control.buttons.needs_attention.getAttribute('aria-pressed'), 'true');
  assert.equal(control.buttons.ok.getAttribute('aria-pressed'), 'false');
  assert.equal(status(), MESSAGES.dirty);
  assert.equal(control.save.disabled, false);
  await control.save.dispatch('click');
  assert.deepEqual(saves, [{ mark: 'needs_attention', memo: null }]);
  assert.equal(status(), '저장됨 · 3분 전');
  assert.equal(control.clear.hidden, false);
  assert.equal(control.save.disabled, true);  // nothing unsaved
  // pressing the pressed mark takes it back: with no memo there is nothing to save, only to clear
  await control.buttons.needs_attention.dispatch('click');
  assert.equal(control.buttons.needs_attention.getAttribute('aria-pressed'), 'false');
  assert.equal(control.save.disabled, true);
  assert.equal(status(), MESSAGES.emptySaved);
  // a memo alone is complete
  const toggle = control.root.find(node => node.hasClass('feedback-memo-toggle'));
  await toggle.dispatch('click');
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  control.area.value = '다시 보니 메모만 남깁니다';
  await control.area.dispatch('input');
  assert.equal(control.save.disabled, false);
  await control.save.dispatch('click');
  assert.deepEqual(saves.at(-1), { mark: null, memo: '다시 보니 메모만 남깁니다' });
  // clearing is its own action and says the history stays
  await control.clear.dispatch('click');
  assert.equal(clears.length, 1);
  assert.equal(status(), MESSAGES.cleared);
  assert.equal(control.clear.hidden, true);
  // a refusal keeps what the owner typed and says why
  const refusing = createFeedbackControl({ document, idPrefix: 'feedback-step',
    onSave: async () => { throw Object.assign(new Error('stale'), { code: 'conflict' }); }, onClear: async () => {} });
  refusing.show({ heading: '이 단계' });
  await refusing.buttons.ok.dispatch('click');
  await refusing.save.dispatch('click');
  assert.match(refusing.status.textContent, /다른 화면에서 이 피드백을 먼저 바꿨습니다/);
  assert.throws(() => createFeedbackControl({ document, idPrefix: 'x', onSave: 1, onClear: 1 }));
});

function mounted(trace) {
  const roots = Object.fromEntries(['summary', 'banner', 'final', 'views', 'graphMount', 'timeline', 'selection',
    'artifactsMount'].map(name => [name, new FakeElement(name === 'final' ? 'section' : 'div')]));
  const posts = [];
  const marks = [];
  let current = trace.feedback ?? { run: null, steps: [] };
  let revisionOffset = 0;
  const request = async (path, options = {}) => {
    if (path.endsWith('/trace')) return structuredClone(trace);
    if (path.endsWith('/feedback') && options.method === 'POST') {
      posts.push(structuredClone(options.body));
      const body = options.body;
      const key = targetKey(body.target);
      const known = key === 'run' ? current.run : current.steps.find(entry => targetKey(entry.target) === key);
      const revision = (known?.revision ?? 0) + revisionOffset;
      if (body.expected_revision !== revision) throw Object.assign(new Error('stale'), { code: 'conflict' });
      const recorded = item(body.target, revision + 1, { mark: body.mark, memo: body.memo,
        state: body.action === 'clear' ? 'cleared' : 'set' });
      current = key === 'run' ? { ...current, run: recorded }
        : { ...current, steps: [...current.steps.filter(entry => targetKey(entry.target) !== key), recorded] };
      return { recorded, replayed: false, current: structuredClone(current) };
    }
    if (path.endsWith('/feedback')) return { current: structuredClone(current), history: [] };
    throw Object.assign(new Error('not in this test'), { code: 'unavailable' });
  };
  let n = 0;
  const detail = createRunDetail({ document, request, basePath: '/', roots, commandId: () => CMD(++n),
    graph: { select() {}, clear() {}, mark: markers => marks.push(new Map(markers)) },
    artifacts: { filter() {} } });
  return { detail, roots, posts, marks, bump: () => { revisionOffset += 1; } };
}

test('the run detail: "이 결과 전체" in the final block, the selected attempt in the panel, markers and a header line', async () => {
  const { detail, roots, posts, marks, bump } = mounted(sampleTrace());
  await detail.show(RUN);
  await tick();
  const runBox = roots.final.find(node => node.getAttribute('data-feedback-for') === 'feedback-run');
  assert.ok(runBox, 'the whole result has its feedback in the final block');
  assert.match(runBox.textContent, /이 결과 전체/);
  const summaryLine = () => roots.summary.find(node => node.hasClass('run-feedback-summary'));
  assert.equal(summaryLine().hidden, true);
  // 확인 필요 on the whole result, no memo
  const button = (box, text) => box.find(node => node.tagName === 'BUTTON' && node.textContent.endsWith(text));
  await button(runBox, '확인 필요').dispatch('click');
  await button(runBox, '저장').dispatch('click');
  await tick();
  assert.deepEqual(posts[0], { schema_version: 'process-feedback-command-v1', command_id: CMD(1), action: 'set',
    target: { scope: 'run' }, expected_revision: 0, mark: 'needs_attention', memo: null });
  assert.equal(summaryLine().hidden, false);
  assert.match(summaryLine().textContent, /결과 전체: 확인 필요/);
  // the store step's attempt 1: the panel's control names the step and the attempt
  detail.select({ nodeId: 'publish', attemptNo: 1 });
  await tick();
  const stepBox = roots.selection.find(node => node.getAttribute('data-feedback-for') === 'feedback-step');
  assert.match(stepBox.textContent, /이 단계: 저장 도구로 기록한다 · 시도 1/);
  await button(stepBox, '괜찮음').dispatch('click');
  const area = stepBox.find(node => node.tagName === 'TEXTAREA');
  area.value = '시도 1은 입력을 제대로 받았습니다';
  await area.dispatch('input');
  await button(stepBox, '저장').dispatch('click');
  await tick();
  assert.deepEqual(posts[1].target, { scope: 'step', node_id: 'publish', visit_no: 1, attempt_no: 1 });
  assert.deepEqual([posts[1].mark, posts[1].memo], ['ok', '시도 1은 입력을 제대로 받았습니다']);
  // the graph and the timeline mark the step and the exact attempt; the header counts it
  assert.equal(marks.at(-1).get('publish').kind, 'ok');
  const row = roots.timeline.find(node => node.tagName === 'BUTTON' && node.getAttribute('data-node') === 'publish'
    && node.getAttribute('data-attempt') === '1');
  assert.equal(row.getAttribute('data-feedback'), 'ok');
  const other = roots.timeline.find(node => node.tagName === 'BUTTON' && node.getAttribute('data-node') === 'publish'
    && node.getAttribute('data-attempt') === '2');
  assert.equal(other.getAttribute('data-feedback'), null);
  assert.match(summaryLine().textContent, /괜찮음 1개 단계/);
  // the whole run selected: no step control (the run's is in the final block)
  detail.select({ nodeId: null });
  assert.equal(roots.selection.find(node => node.hasClass('selection-feedback')).hidden, true);
  // a stale revision is refused and the server's latest replaces the draft
  detail.select({ nodeId: 'publish', attemptNo: 1 });
  bump();
  await button(stepBox, '괜찮음').dispatch('click');  // take the mark back
  await button(stepBox, '확인 필요').dispatch('click');
  await button(stepBox, '저장').dispatch('click');
  await tick();
  assert.match(stepBox.textContent, /다른 화면에서 이 피드백을 먼저 바꿨습니다/);
});

test('without a command id source the detail is read-only: no feedback controls, the markers still show', async () => {
  const trace = sampleTrace();
  trace.feedback = { run: null, steps: [item(stepTarget('intake', 1), 1, { mark: 'needs_attention' })] };
  const roots = Object.fromEntries(['summary', 'banner', 'final', 'views', 'graphMount', 'timeline', 'selection']
    .map(name => [name, new FakeElement('div')]));
  const marks = [];
  const detail = createRunDetail({ document, roots, basePath: '/', graph: { select() {}, clear() {}, mark: m => marks.push(m) },
    request: async path => (path.endsWith('/trace') ? structuredClone(trace) : Promise.reject(new Error('x'))) });
  await detail.show(RUN);
  assert.equal(roots.final.find(node => node.getAttribute('data-feedback-for')), null);
  assert.equal(marks.at(-1).get('intake').kind, 'needs_attention');
  assert.match(roots.summary.textContent, /확인 필요 1개 단계/);
  const row = roots.timeline.find(node => node.tagName === 'BUTTON' && node.getAttribute('data-node') === 'intake'
    && node.getAttribute('data-kind') === 'visit');
  assert.equal(row.getAttribute('data-feedback'), 'needs_attention');
});
