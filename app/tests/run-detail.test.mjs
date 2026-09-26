// UI phase 3 (DOM half): the run detail screen (run-detail.mjs) over a fake document and a
// synthetic run-trace-v1 payload. It checks the behaviour the redesign names (§5.3): the final
// result comes first and opens "내 버전" in place with a title naming the artifact, role and
// step; one selection drives the graph, the timeline and the tabs; selecting a node shows THAT
// node's outputs; a past attempt shows its own inputs, error and calls and never the latest
// attempt's outputs; a pending approval is a banner. Text only, never markup.

import test from 'node:test';
import assert from 'node:assert/strict';

process.env.TZ = 'Asia/Seoul';

const { createRunDetail, DETAIL_TABS, MESSAGES } = await import('../static/run-detail.mjs');
const { RUN, art, id, sampleTrace } = await import('./helpers/run-trace-sample.mjs');

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.dataset = {};
    this.hidden = false;
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

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  dispatch(type, event = {}) {
    for (const listener of this.listeners.get(type) ?? []) listener({ ...event, preventDefault() {} });
  }

  focus() {}

  scrollIntoView() { this.scrolled = (this.scrolled ?? 0) + 1; }

  hasClass(name) { return (this.getAttribute('class') ?? '').split(/\s+/).includes(name); }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }

  find(predicate) { return this.findAll(predicate)[0] ?? null; }

  // the only selector the detail asks for: 'button.timeline-entry'
  querySelectorAll(selector) {
    const [tag, className] = selector.split('.');
    return this.findAll(node => node.tagName === tag.toUpperCase() && node.hasClass(className));
  }
}

const document = { createElement: tag => new FakeElement(tag) };
const tick = () => new Promise(resolve => setImmediate(resolve));

function byLabel(root, label) {
  return root.find(node => node.getAttribute('aria-label') === label);
}

function buttonText(root, text) {
  return root.find(node => node.tagName === 'BUTTON' && node.textContent === text);
}

// the latest attempt of the store step recorded a receipt; attempt 1 recorded nothing
function twoAttemptTrace(overrides = {}) {
  const trace = sampleTrace(overrides);
  const receipt = art(410, 'receipt', 'application/json');
  const publish = trace.nodes.find(node => node.node_id === 'publish');
  publish.visits[0].attempts[1].outputs = [receipt];
  publish.visits[0].outputs = [receipt];
  return { trace, receipt };
}

function mounted({ trace = twoAttemptTrace().trace, previews = true } = {}) {
  const roots = Object.fromEntries(['summary', 'banner', 'final', 'views', 'graphMount', 'timeline', 'selection',
    'artifactsMount'].map(name => [name, new FakeElement(name === 'final' ? 'section' : 'div')]));
  const requests = [];
  const filters = [];
  const graphCalls = [];
  const edits = [];
  const approvalsOpened = [];
  const selections = [];
  const request = async (path, options) => {
    requests.push([path, options]);
    if (path.endsWith('/trace')) return structuredClone(trace);
    if (!previews) throw Object.assign(new Error('no preview'), { code: 'unavailable' });
    throw Object.assign(new Error('preview not in this test'), { code: 'unavailable' });
  };
  const detail = createRunDetail({
    document, request, basePath: '/', roots,
    graph: { select: (nodeId, options) => graphCalls.push(['select', nodeId, options]), clear: () => graphCalls.push(['clear']) },
    artifacts: { filter: (ids, options) => filters.push([ids === null ? null : [...ids], options]) },
    onEdit: (runId, listed, context) => edits.push({ runId, listed, context }),
    onAlternativeFile: () => {},
    onOpenApprovals: () => approvalsOpened.push(true),
    onSelectionChange: (selection, view) => selections.push([selection, view.scope]),
  });
  return { detail, roots, requests, filters, graphCalls, edits, approvalsOpened, selections };
}

function panel(roots, tabId) {
  return roots.selection.find(node => node.getAttribute('id') === `detail-${tabId}-panel`);
}

test('the detail refuses a missing document, request adapter or mount', () => {
  assert.throws(() => createRunDetail({ request: async () => ({}) }), /document/);
  assert.throws(() => createRunDetail({ document, roots: {} }), /request/);
  assert.throws(() => createRunDetail({ document, request: async () => ({}), roots: { summary: new FakeElement('div') } }), /mount/);
  assert.deepEqual(DETAIL_TABS.map(([, label]) => label), ['입력', '산출물', '전달', '도구·모델', '기록']);
});

test('the header names the work and phase in words, and the final result comes first with an in-place edit', async () => {
  const { detail, roots, requests, filters, edits } = mounted();
  await detail.show(RUN);
  await tick();
  assert.equal(requests[0][0], `/api/v1/runs/${RUN}/trace`);
  const summary = roots.summary.textContent;
  assert.match(summary, /화요일 공간 안내/);
  assert.match(summary, /완료/);
  assert.match(summary, /걸린 시간 22초/);
  assert.match(summary, /모델 호출 1회 · 도구 호출 2회 · 시도 2회\(재시도 1회\)/);
  assert.match(summary, /미확인/);
  // raw ids and digests only inside "기술 정보"
  const technical = roots.summary.find(node => node.tagName === 'DETAILS');
  assert.ok(technical.textContent.includes(RUN));
  assert.equal(roots.banner.hidden, true);
  // the final result: the exit node's report, with a preview request, a download and "내 버전 만들기"
  const card = roots.final.find(node => node.getAttribute('data-artifact-id') === id(300));
  assert.ok(card, 'the report is the final result');
  assert.match(roots.final.textContent, /최종 결과/);
  assert.match(card.textContent, /“최종 보고서로 묶는다” 단계\(report\)가 만듦/);
  assert.ok(requests.some(([path]) => path === `/api/v1/runs/${RUN}/artifacts/${id(300)}/preview`));
  const download = card.find(node => node.tagName === 'A' && node.textContent === '원본 내려받기');
  assert.equal(download.getAttribute('href'), `/api/v1/runs/${RUN}/artifacts/${id(300)}/content`);
  buttonText(card, '내 버전 만들기').dispatch('click');
  await tick();
  assert.equal(edits.length, 1);
  assert.equal(edits[0].runId, RUN);
  assert.equal(edits[0].listed.artifactId, id(300));
  assert.equal(edits[0].context.title, 'report (최종 보고서로 묶는다 · 수행 1)');
  assert.equal(edits[0].context.anchor, card);
  assert.ok(card.children.includes(edits[0].context.slot), 'the editor opens inside the card, not on another page');
  // with nothing selected the outputs tab lists the whole run
  assert.deepEqual(filters.at(-1)[0], null);
  assert.match(panel(roots, 'outputs').textContent, /이 실행이 남긴 산출물 전체/);
});

test('selecting a node shows THAT node\'s outputs, and the graph mirrors the selection without a loop', async () => {
  const { detail, roots, filters, graphCalls, selections } = mounted();
  await detail.show(RUN);
  detail.select({ nodeId: 'writer' });
  await tick();
  assert.deepEqual(filters.at(-1)[0], [id(200)]);
  assert.equal(filters.at(-1)[1].nodeId, 'writer');
  assert.deepEqual(graphCalls.at(-1), ['select', 'writer', { notify: false }]);
  assert.match(roots.selection.textContent, /안내문 초안을 쓴다/);
  // a selection that came from the graph is not echoed back to it
  const before = graphCalls.length;
  detail.select({ nodeId: 'intake' }, { fromGraph: true });
  await tick();
  assert.equal(graphCalls.length, before);
  assert.deepEqual(filters.at(-1)[0], [id(100)]);
  // back to the whole run clears the graph and the filter
  buttonText(roots.selection, '실행 전체 보기').dispatch('click');
  await tick();
  assert.deepEqual(graphCalls.at(-1), ['clear']);
  assert.equal(filters.at(-1)[0], null);
  assert.deepEqual(selections.map(([, scope]) => scope), ['run', 'visit', 'visit', 'run']);
});

test('the latest attempt is the default; a past attempt shows its own inputs, error and calls and none of the latest outputs', async () => {
  const { trace, receipt } = twoAttemptTrace();
  const { detail, roots, filters } = mounted({ trace });
  await detail.show(RUN);
  detail.select({ nodeId: 'publish' });
  await tick();
  const picker = byLabel(roots.selection, '시도 선택');
  assert.equal(picker.value, '2');
  assert.deepEqual(picker.children.map(option => option.textContent), ['시도 1 (실패)', '시도 2 (완료, 최신)']);
  assert.deepEqual(filters.at(-1)[0], [receipt.artifact_id]);
  assert.equal(filters.at(-1)[1].label, '시도 2의');
  assert.equal(roots.selection.find(node => node.hasClass('selection-error')), null);
  // switch to attempt 1 with the picker
  picker.value = '1';
  picker.dispatch('change');
  await tick();
  assert.deepEqual(detail.selection, { nodeId: 'publish', visitNo: 1, attemptNo: 1 });
  assert.deepEqual(filters.at(-1)[0], [], 'attempt 1 never lists attempt 2\'s receipt');
  assert.equal(filters.at(-1)[1].label, '시도 1의');
  const error = roots.selection.find(node => node.hasClass('selection-error'));
  assert.match(error.textContent, /시도 1 오류/);
  assert.match(error.textContent, /도구·제공자의 응답으로 끝남/);
  assert.ok(roots.selection.find(node => node.hasClass('past-attempt')));
  // its inputs are the writer's exact draft, with the step it came from
  const inputs = panel(roots, 'inputs').textContent;
  assert.match(inputs, /앞 단계 “안내문 초안을 쓴다” \(writer\)/);
  assert.match(inputs, /draft/);
  // its calls are attempt 1's tool call only
  const calls = panel(roots, 'calls');
  assert.ok(calls.textContent.includes(id(601)));
  assert.ok(!calls.textContent.includes(id(602)));
  assert.match(calls.textContent, /시도 1의 예약과 비용/);
  // its records are attempt 1's journal, with the records page filtered to this run
  const records = panel(roots, 'records');
  assert.match(records.textContent, /시도 1의 기록/);
  const link = records.find(node => node.tagName === 'A');
  assert.equal(link.getAttribute('href'), `./records.html#run=${RUN}`);
});

test('the tools and models tab shows the model call with its tokens, the unknown cost and no hidden reasoning', async () => {
  const { detail, roots } = mounted();
  await detail.show(RUN);
  detail.select({ nodeId: 'writer' }, { tab: 'calls' });
  const calls = panel(roots, 'calls');
  assert.equal(calls.hidden, false, 'the tab was switched to 도구·모델');
  assert.match(calls.textContent, /모델 호출/);
  assert.match(calls.textContent, /입력 812 · 출력 164/);
  assert.match(calls.textContent, /미확인/);
  // the not-recorded cost says why, in the owner's words
  assert.match(calls.textContent, /상한 단가도 없어 이 모델 호출의 비용은 기록하지 않았습니다/);
  assert.match(calls.textContent, /숨은 추론은 저장하지 않으므로/);
});

test('a model call priced at the configured ceiling is labelled an estimate with its rates, never a charge', async () => {
  const { trace } = twoAttemptTrace();
  const call = trace.nodes[1].visits[0].model_calls[0];
  call.cost = { state: 'estimate', basis: 'reserved_ceiling', method: 'recorded_tokens_at_ceiling_rates',
    microunits: 6_528, currency: 'USD', rates: { currency: 'USD', unit: 'microunits_per_million_tokens',
      input_microunits_per_mtok: 4_000_000, output_microunits_per_mtok: 20_000_000,
      cache_creation_microunits_per_mtok: null, cache_read_microunits_per_mtok: null } };
  const { detail, roots } = mounted({ trace });
  await detail.show(RUN);
  detail.select({ nodeId: 'writer' }, { tab: 'calls' });
  const text = panel(roots, 'calls').textContent;
  assert.match(text, /약 \$0\.0065 \(기록된 토큰 × 설정된 상한 단가 추정\)/);
  assert.match(text, /입력 \$4 · 출력 \$20 \(100만 토큰당\)/);
  assert.doesNotMatch(text, /비용은 기록하지 않았습니다/);
  assert.doesNotMatch(text, /정산 기록/);
  // a subscription run's call states its basis instead
  call.cost = { state: 'unknown', basis: 'subscription_mode' };
  const subscription = mounted({ trace });
  await subscription.detail.show(RUN);
  subscription.detail.select({ nodeId: 'writer' }, { tab: 'calls' });
  assert.match(panel(subscription.roots, 'calls').textContent, /미확인 \(구독 방식: 호출별 금액 없음\)/);
});

test('a model attempt shows the tokens its provider reported, or says they are not recorded', async () => {
  const { trace } = twoAttemptTrace();
  const [first, second] = trace.nodes[2].visits[0].attempts;
  for (const attempt of [first, second]) attempt.budget_reservation.reserved.model_calls = 1;
  second.tokens = { input: 812, output: 164, cache_creation_input: 0, cache_read_input: 0 };
  second.observed_model = 'synthetic-model-1';
  const { detail, roots } = mounted({ trace });
  await detail.show(RUN);
  detail.select({ nodeId: 'publish', attemptNo: 2 }, { tab: 'calls' });
  const latest = panel(roots, 'calls').textContent;
  assert.match(latest, /시도 2의 예약과 비용.*토큰입력 812 · 출력 164/s);
  assert.match(latest, /synthetic-model-1/);
  detail.select({ nodeId: 'publish', attemptNo: 1 }, { tab: 'calls' });
  assert.match(panel(roots, 'calls').textContent, /토큰기록 없음 — 이 모델 시도는 전송 경로가 제공자의 토큰 수를 알리지 않아/);
});

test('the timeline shares the selection: its entry selects the attempt and is marked pressed', async () => {
  const { detail, roots } = mounted();
  await detail.show(RUN);
  const entries = roots.timeline.querySelectorAll('button.timeline-entry');
  assert.equal(entries.length, 4);
  const first = entries.find(node => node.getAttribute('data-kind') === 'attempt' && node.getAttribute('data-attempt') === '1');
  first.dispatch('click');
  assert.deepEqual(detail.selection, { nodeId: 'publish', visitNo: 1, attemptNo: 1 });
  assert.equal(first.getAttribute('aria-pressed'), 'true');
  assert.deepEqual(entries.filter(node => node.getAttribute('aria-pressed') === 'true'), [first]);
  // the unrecorded facts are named as such
  assert.match(roots.timeline.textContent, /기록하지 않는 것 2가지/);
});

test('a pending approval is a banner with a way to the approval screen', async () => {
  const pending = sampleTrace();
  pending.phase = 'waiting';
  pending.approvals.gates[0].state = 'pending';
  const { detail, roots, approvalsOpened } = mounted({ trace: pending });
  await detail.show(RUN);
  assert.equal(roots.banner.hidden, false);
  assert.match(roots.banner.textContent, /사람 승인이 필요합니다/);
  assert.match(roots.banner.textContent, /tool-gate/);
  buttonText(roots.banner, '승인 화면 열기').dispatch('click');
  assert.equal(approvalsOpened.length, 1);
});

test('without a final result the section says so and names where the run stopped', async () => {
  const stopped = sampleTrace({ phase: 'stopped', final_results: [], stopped_at: [{ node_id: 'publish', state: 'failed' }] });
  stopped.nodes.find(node => node.node_id === 'publish').state = 'failed';
  const { detail, roots } = mounted({ trace: stopped });
  await detail.show(RUN);
  assert.match(roots.final.textContent, new RegExp(MESSAGES.noFinal));
  const where = byLabel(roots.final, '멈춘 지점');
  assert.ok(where, 'the stopped places are listed');
  buttonText(where, '저장 도구로 기록한다 (publish)').dispatch('click');
  assert.equal(detail.selection.nodeId, 'publish');
});

test('a trace outside the contract is an honest failure, never half shown', async () => {
  const { detail, roots } = mounted({ trace: { schema_version: 'run-trace-v0' } });
  await assert.rejects(detail.show(RUN));
  assert.match(roots.summary.textContent, new RegExp(MESSAGES.failed));
  assert.equal(detail.trace, null);
  assert.equal(detail.select({ nodeId: 'publish' }), null);
});

test('a pick made while the trace is being read is applied once it arrives; a new read of the same run keeps it', async () => {
  const { detail, filters, graphCalls } = mounted();
  const shown = detail.show(RUN);
  assert.equal(detail.select({ nodeId: 'writer' }, { fromGraph: true }), null);
  await shown;
  await tick();
  assert.equal(detail.selection.nodeId, 'writer');
  assert.deepEqual(filters.at(-1)[0], [id(200)]);
  assert.equal(graphCalls.length, 0, 'the graph made the pick; it is not echoed back');
  await detail.show(RUN);
  assert.equal(detail.selection.nodeId, 'writer');
  detail.reset();
  assert.equal(detail.select({ nodeId: 'writer' }), null);
});

test('a pick in the graph or timeline brings the panel into view only when it sits under the views', async () => {
  const { detail, roots } = mounted();
  await detail.show(RUN);
  roots.views.getBoundingClientRect = () => ({ top: 0, bottom: 600 });
  roots.selection.getBoundingClientRect = () => ({ top: 0, bottom: 900 });  // side by side
  detail.select({ nodeId: 'writer' }, { fromGraph: true, reveal: true });
  assert.equal(roots.selection.scrolled, undefined);
  roots.selection.getBoundingClientRect = () => ({ top: 640, bottom: 1400 });  // stacked
  detail.select({ nodeId: 'intake' }, { fromGraph: true, reveal: true });
  assert.equal(roots.selection.scrolled, 1);
  roots.timeline.querySelectorAll('button.timeline-entry')[0].dispatch('click');
  assert.equal(roots.selection.scrolled, 2);
});
