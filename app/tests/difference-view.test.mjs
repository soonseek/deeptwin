// UI phase 4 (§5.5, experience.md §8): "차이 살펴보기" (difference-view.mjs) over a fake document
// and a fake request. The first screen is the observed differences, the evidence scope with the
// unreviewed area, and the related run segment (run-trace.mjs differenceSegment: the step, its
// attempt, its inputs and its tool/model calls). Picking a difference shows the original part,
// the owner's part and the context around it. The inquiry panel sits inside and asks nothing of
// a model until the owner explicitly requests explanations. Text only, never markup.

import test from 'node:test';
import assert from 'node:assert/strict';

const { createDifferenceView, differenceParts, scopeText, splitLines } = await import('../static/difference-view.mjs');
const { differenceSegment } = await import('../static/run-trace.mjs');
const { RUN, id, sampleTrace } = await import('./helpers/run-trace-sample.mjs');

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.dataset = {};
    this.hidden = false;
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

  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }

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
    const match = /^(\w+)\[([\w-]+)\]$/.exec(selector);
    return match ? this.findAll(node => node.tagName === match[1].toUpperCase() && node.attributes.has(match[2])) : [];
  }
}

const document = { createElement: tag => new FakeElement(tag) };
const ORIGINAL = '# 안내\n\n- 장소: 3층 세미나실\n- 시간: 화요일 14:00\n- 준비물: 노트북\n\n문의는 운영팀에.\n';
const MINE = '# 안내\n\n- 장소: 4층 큰 회의실\n- 시간: 화요일 14:00\n- 준비물: 노트북\n\n문의는 운영팀에.\n추가 줄\n';

test('the parts of a text difference: the original lines, the owner\'s lines and three lines around', () => {
  assert.deepEqual(splitLines('a\nb\n'), ['a', 'b']);
  assert.deepEqual(splitLines('a\r\nb'), ['a', 'b']);
  assert.deepEqual(splitLines(''), []);
  const texts = { format: 'text', original: ORIGINAL, mine: MINE };
  const replaced = differenceParts({ locator: { operation: 'replace', original_lines: [3, 3], alternative_lines: [3, 3] } }, texts);
  assert.equal(replaced.kind, 'text');
  assert.equal(replaced.label, '원본 3–3행 → 내 버전 3–3행');
  assert.deepEqual(replaced.original, [{ no: 3, text: '- 장소: 3층 세미나실' }]);
  assert.deepEqual(replaced.mine, [{ no: 3, text: '- 장소: 4층 큰 회의실' }]);
  assert.deepEqual(replaced.context.map(line => [line.no, line.mark]),
    [[1, ' '], [2, ' '], [3, '-'], [3, '+'], [4, ' '], [5, ' '], [6, ' ']]);
  // an insertion has no original part; its context is the lines before it
  const inserted = differenceParts({ locator: { operation: 'insert', original_lines: [8, 7], alternative_lines: [8, 8] } }, texts);
  assert.deepEqual(inserted.original, []);
  assert.deepEqual(inserted.mine, [{ no: 8, text: '추가 줄' }]);
  // a locator outside the texts is never guessed at
  assert.equal(differenceParts({ locator: { original_lines: [30, 31], alternative_lines: [1, 1] } }, texts).kind, 'none');
  // no texts (an uploaded file) and unsupported formats say so
  assert.match(differenceParts({ locator: {} }, null).reason, /정렬 미정/);
  assert.match(differenceParts({ locator: { path: '/a' } }, { format: 'json' }).reason, /관측 설명만/);
  // the owner kept typing while the freeze was sent: the frozen content is not known here
  assert.match(differenceParts({ locator: { original_lines: [3, 3], alternative_lines: [3, 3] } },
    { format: null, original: ORIGINAL, mine: null }).reason, /확실히 알 수 없습니다/);
  const table = differenceParts({ locator: { original_row: 2, alternative_row: 2, column: 2 } },
    { format: 'table', original: [['이름', '값'], ['a', '1']], mine: [['이름', '값'], ['a', '2']] });
  assert.deepEqual([table.original[0].text, table.mine[0].text], ['1', '2']);
  assert.equal(scopeText({ evidence_scope: ['s1'] }),
    '내가 바꾼 1곳이 근거입니다. 바꾸지 않은 부분은 검토하지 않은 영역으로 남고, 영향 범위는 따로 조사합니다.');
  assert.match(scopeText({ evidence_scope: ['whole'] }), /^내 버전 전체가 근거입니다/);
});

test('the related run segment is the step, its attempt, its exact inputs and its calls, from the trace only', () => {
  const trace = sampleTrace();
  const publish = differenceSegment(trace, { nodeId: 'publish', visitNo: 1, attemptNo: 1 });
  assert.equal(publish.responsibility, '저장 도구로 기록한다');
  assert.deepEqual([publish.visitNo, publish.attemptNo, publish.attempts], [1, 1, 2]);
  assert.deepEqual(publish.inputs.map(item => [item.nodeId, item.attemptNo, [...item.roles]]), [['writer', null, ['draft']]]);
  assert.deepEqual(publish.tools.map(item => [item.toolId, item.attemptNo, item.state]), [['test_actor_notify', 1, '실패']]);
  assert.match(publish.error, /실패/);
  const writer = differenceSegment(trace, { nodeId: 'writer' });
  assert.equal(writer.attemptNo, null);
  assert.deepEqual(writer.models.map(item => item.tokens), ['입력 812 · 출력 164 토큰']);
  assert.equal(differenceSegment(trace, { nodeId: 'nowhere' }), null);
  assert.equal(differenceSegment(null, { nodeId: 'writer' }), null);
});

const DIFFERENCE = {
  difference_ref: { kind: 'difference', id: id(990), version: 1, sha256: 'e'.repeat(64) }, alternative_id: id(980),
  observations: [
    { observation_id: 'obs-1', kind: 'text_change', description: '원본 3–3행이 대안 3–3행으로 바뀌었다.',
      locator: { operation: 'replace', original_lines: [3, 3], alternative_lines: [3, 3], alignment: 'proposed' } },
    { observation_id: 'obs-2', kind: 'text_change', description: '대안 8–8행이 원본에 없다.',
      locator: { operation: 'insert', original_lines: [8, 7], alternative_lines: [8, 8], alignment: 'proposed' } },
  ],
  uncertainties: ['위치 대응은 제안된 정렬이다.'], evidence_scope: ['s1', 's2'], unreviewed_scope: ['rest'],
  impact_scope: 'pending_investigation',
  hypotheses: { state: 'not_generated', families: ['system', 'expert_judgment'], reason: '소유자가 요청할 때만 만든다.' },
  inquiry: { state: 'not_opened', reason: '탐구는 직접 열 때만 열린다.' },
  change_candidates: { state: 'none', reason: '변경 후보를 만들지 않았다.' },
};

test('the view reads (or once observes) the difference, shows it with the run segment, and calls no model', async () => {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options = {}) => {
    asked.push([options.method ?? 'GET', path]);
    if (path.endsWith('/difference') && (options.method ?? 'GET') === 'GET') throw Object.assign(new Error('none yet'), { code: 'not_found' });
    if (path.endsWith('/difference')) return structuredClone(DIFFERENCE);
    if (path.endsWith('/hypotheses')) return { state: 'not_generated' };
    if (path.endsWith('/connections/claude')) return { key_present: false };
    throw Object.assign(new Error('unexpected'), { code: 'not_found' });
  };
  const picked = [];
  const view = createDifferenceView({ root, document, request, basePath: '/', crypto: { randomUUID: () => id(1) },
    onSelectStep: target => picked.push(target), onClose: () => {} });
  const segment = differenceSegment(sampleTrace(), { nodeId: 'report' });
  await view.show({ runId: RUN, artifactId: id(300), alternativeId: id(980), title: 'report (최종 보고서로 묶는다 · 수행 1)',
    texts: { format: 'text', original: ORIGINAL, mine: MINE }, segment });
  const text = root.textContent;
  assert.match(text, /차이 살펴보기 — report \(최종 보고서로 묶는다 · 수행 1\)/);
  assert.match(text, /관측된 차이 2개/);
  assert.match(text, /내가 바꾼 2곳이 근거입니다\. 바꾸지 않은 부분은 검토하지 않은 영역으로 남고, 영향 범위는 따로 조사합니다\./);
  assert.match(text, /관련 실행 구간“최종 보고서로 묶는다” \(report\) · 수행 1 · 시도 기록 없음/);
  assert.match(text, /앞 단계 “저장 도구로 기록한다”\(publish\) 시도 2/);
  // the first difference is shown with its parts; the explanations stay unmade and unasked
  assert.match(text, /고른 차이: 원본 3–3행 → 내 버전 3–3행/);
  assert.match(text, /원본 부분3 - 장소: 3층 세미나실/);
  assert.match(text, /3−- 장소: 3층 세미나실 \(원본에서 바뀐 줄\)3\+- 장소: 4층 큰 회의실 \(내 버전의 줄\)/);
  assert.match(text, /내 버전 부분3 - 장소: 4층 큰 회의실/);
  assert.match(text, /설명과 탐구/);
  assert.match(text, /소유자가 요청할 때만 만든다/);
  assert.equal(root.find(node => node.getAttribute('id') === 'run-inquiry') !== null, true);
  // observed once through the server's own route; nothing asked a model for anything
  assert.deepEqual(asked.filter(([method]) => method === 'POST').map(([, path]) => path),
    [`/api/v1/runs/${RUN}/artifacts/${id(300)}/alternatives/${id(980)}/difference`]);
  assert.ok(!asked.some(([method, path]) => method === 'POST' && /hypotheses|model-choice|inquiries/.test(path)));
  // picking the second difference shows the owner's added line
  const second = root.find(node => node.getAttribute('data-observation') === 'obs-2');
  await second.dispatch('click');
  assert.equal(second.getAttribute('aria-pressed'), 'true');
  assert.match(root.textContent, /고른 차이: 원본 8–7행 → 내 버전 8–8행/);
  assert.match(root.textContent, /\(원본에는 없는 줄\)/);
  // the segment links back to the process view
  await root.find(node => node.tagName === 'BUTTON' && node.textContent === '과정에서 이 단계 보기').dispatch('click');
  assert.deepEqual(picked, [{ nodeId: 'report', visitNo: 1, attemptNo: null }]);
  // an uploaded file (no texts) shows the observation only, and says why
  await view.show({ runId: RUN, artifactId: id(300), alternativeId: id(980), texts: null, segment: null });
  assert.match(root.textContent, /정렬 미정/);
  assert.match(root.textContent, /이 산출물을 만든 단계의 기록을 찾지 못했습니다/);
});
