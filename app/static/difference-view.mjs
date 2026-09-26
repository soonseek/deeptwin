// UI phase 4 (docs/ui/2026-09-26-product-ux-redesign.md §5.5, experience.md §8): "차이 살펴보기".
// After the owner freezes their own version (alternatives.mjs / alternative-file.mjs), this view
// opens in place, directly under the artifact the owner answered — not in a card at the page
// bottom. Its first screen is what was observed and where in the run it happened:
//   - the observed differences (the sealed `difference` record: positions and operations, never
//     a reason) and the evidence scope — what the owner changed is the evidence, the rest stays
//     unreviewed, and the impact is still to be investigated;
//   - the related run segment: the step that made the artifact, its visit and attempt, the exact
//     inputs it received and its tool and model calls (run-trace.mjs differenceSegment).
// Selecting a difference shows the original part, the owner's part and the surrounding lines.
// Below, the inquiry panel (inquiry.mjs, embedded): competing explanations only on the owner's
// explicit request (they stay `proposed`), the inquiry's optional questions, evidence and
// judgments, and change-candidate proposals that are never applied here. Opening this view
// reads and, once, observes the difference; it never calls a model. All text reaches the DOM
// through textContent.

import { createInquiryPanel, differenceRoute, MESSAGES as INQUIRY_MESSAGES, ERROR_MESSAGES } from './inquiry.mjs';
import { el } from './ui-parts.mjs';

export const CONTEXT_LINES = 3;
export const MESSAGES = Object.freeze({
  observing: '차이를 관측하는 중…',
  observed: '관측한 차이입니다. 원인은 아직 해석하지 않았습니다.',
  noSegment: '이 산출물을 만든 단계의 기록을 찾지 못했습니다.',
  noParts: '이 형식은 부분을 나눠 보이지 않습니다. 관측 설명만 봅니다.',
  noTexts: '올린 파일과 원본의 부분 대응은 계산하지 않았습니다(정렬 미정). 관측 설명만 봅니다.',
  moving: '고정하는 동안 내용이 바뀌어 고정한 두 내용을 확실히 알 수 없습니다. 관측 설명만 봅니다.',
  alignment: '위치는 제안된 정렬입니다. 차이가 왜 생겼는지는 아직 해석하지 않았습니다.',
  firstScreen: '먼저 무엇이 달라졌는지와 그 결과를 만든 실행 구간을 봅니다. 차이를 고르면 원본 부분, 내 버전 부분, 앞뒤 문맥이 나옵니다.',
});

function fail(message) {
  throw Object.assign(new Error(message), { code: 'invalid_input' });
}

// lines as a reader counts them (a final line break ends the last line, it opens no new one)
export function splitLines(text) {
  const value = String(text ?? '');
  if (value === '') return [];
  const lines = value.split(/\r\n|\r|\n/);
  if (/(?:\r\n|\r|\n)$/.test(value)) lines.pop();
  return lines;
}

const inRange = (span, count) => Array.isArray(span) && span.length === 2 && Number.isSafeInteger(span[0])
  && Number.isSafeInteger(span[1]) && span[0] >= 1 && span[1] <= count;

// the original part, the owner's part and a unified context around one observation, or a
// reason why no part can be shown; nothing is realigned or guessed
export function differenceParts(observation, texts, context = CONTEXT_LINES) {
  const locator = observation?.locator ?? {};
  if (!texts) return Object.freeze({ kind: 'none', reason: MESSAGES.noTexts });
  if (texts.format === null || texts.mine === null) return Object.freeze({ kind: 'none', reason: MESSAGES.moving });
  if (texts.format !== 'text' && texts.format !== 'table') return Object.freeze({ kind: 'none', reason: MESSAGES.noParts });
  if (texts.format === 'text' && Array.isArray(locator.original_lines)) {
    const left = splitLines(texts.original);
    const right = splitLines(texts.mine);
    const [s, e] = locator.original_lines;
    const [as, ae] = locator.alternative_lines ?? [1, 0];
    if (!inRange([s, Math.max(s - 1, e)], left.length) || !inRange([as, Math.max(as - 1, ae)], right.length)) {
      return Object.freeze({ kind: 'none', reason: MESSAGES.noParts });
    }
    const numbered = (lines, from, to) => lines.slice(from - 1, to).map((text, index) => ({ no: from + index, text }));
    const original = numbered(left, s, e);
    const mine = numbered(right, as, ae);
    const before = numbered(left, Math.max(1, s - context), s - 1);
    const after = numbered(left, e + 1, Math.min(left.length, e + context));
    const lines = [
      ...before.map(line => ({ ...line, mark: ' ' })),
      ...original.map(line => ({ ...line, mark: '-' })),
      ...mine.map(line => ({ ...line, mark: '+' })),
      ...after.map(line => ({ ...line, mark: ' ' })),
    ];
    return Object.freeze({ kind: 'text', original, mine, context: lines,
      label: `원본 ${s}–${e}행 → 내 버전 ${as}–${ae}행` });
  }
  if (texts.format === 'table' && Number.isSafeInteger(locator.original_row)) {
    const row = (rows, index) => (Array.isArray(rows) && Array.isArray(rows[index - 1]) ? rows[index - 1] : null);
    const before = row(texts.original, locator.original_row);
    const after = row(texts.mine, locator.alternative_row);
    const column = locator.column;
    const cell = (cells, index) => (cells && index >= 1 && index <= cells.length ? String(cells[index - 1]) : '(칸 없음)');
    return Object.freeze({ kind: 'table', label: `원본 ${locator.original_row}행 ${column}열 → 내 버전 ${locator.alternative_row}행 ${column}열`,
      original: [{ no: locator.original_row, text: cell(before, column) }],
      mine: [{ no: locator.alternative_row, text: cell(after, column) }],
      context: [
        { no: locator.original_row, mark: '-', text: before ? before.join(', ') : '(행 없음)' },
        { no: locator.alternative_row, mark: '+', text: after ? after.join(', ') : '(행 없음)' },
      ] });
  }
  return Object.freeze({ kind: 'none', reason: MESSAGES.noParts });
}

// "내가 바꾼 1곳이 근거입니다. 바꾸지 않은 부분은 검토하지 않은 영역으로 남고, 영향 범위는 따로 조사합니다."
export function scopeText(value) {
  const scope = Array.isArray(value?.evidence_scope) && value.evidence_scope.includes('whole')
    ? '내 버전 전체가 근거입니다.' : `내가 바꾼 ${Array.isArray(value?.evidence_scope) ? value.evidence_scope.length : 0}곳이 근거입니다.`;
  return `${scope} ${INQUIRY_MESSAGES.unreviewed}`;
}

export function createDifferenceView({ root, document, request, basePath = '/', crypto = null, onClose = null,
  onSelectStep = null } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  const heading = el(document, 'h3', { className: 'difference-title', text: '차이 살펴보기' });
  const close = el(document, 'button', { className: 'btn btn-quiet', text: '닫기', attrs: { type: 'button' } });
  close.hidden = typeof onClose !== 'function';
  close.addEventListener('click', () => { if (typeof onClose === 'function') onClose(); });
  const status = el(document, 'p', { className: 'difference-status', attrs: { role: 'status', 'aria-live': 'polite' } });
  const scope = el(document, 'p', { className: 'difference-scope' });
  const observed = el(document, 'section', { className: 'difference-observed', attrs: { 'aria-label': '관측된 차이' } });
  const segmentBox = el(document, 'section', { className: 'difference-segment', attrs: { 'aria-label': '관련 실행 구간' } });
  const detail = el(document, 'section', { className: 'difference-detail', attrs: { 'aria-label': '고른 차이' } });
  const inquiryRoot = el(document, 'section', { className: 'difference-explain', attrs: { id: 'run-inquiry',
    'aria-label': '설명과 탐구' } });
  const inquiry = createInquiryPanel({ root: inquiryRoot, document, request, basePath, crypto, embedded: true });
  root.replaceChildren(
    el(document, 'div', { className: 'difference-head' }, [heading, close]),
    el(document, 'p', { className: 'difference-lead', text: MESSAGES.firstScreen }), status, scope,
    el(document, 'div', { className: 'difference-grid' }, [observed, segmentBox]), detail, inquiryRoot);
  let value = null;
  let texts = null;
  let chosen = null;
  let generation = 0;

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function lineList(lines, className) {
    return el(document, 'ol', { className: `difference-lines ${className}` }, lines.map(line => el(document, 'li', {
      attrs: { 'data-mark': line.mark ?? '' } }, [
      el(document, 'span', { className: 'difference-no', text: String(line.no), attrs: { 'aria-hidden': 'true' } }),
      el(document, 'span', { className: 'difference-sign', text: line.mark === '-' ? '−' : line.mark === '+' ? '+' : ' ',
        attrs: { 'aria-hidden': 'true' } }),
      el(document, 'span', { className: 'difference-line', text: line.text === '' ? ' ' : line.text }),
      line.mark === '-' ? el(document, 'span', { className: 'visually-hidden', text: ' (원본에서 바뀐 줄)' })
        : line.mark === '+' ? el(document, 'span', { className: 'visually-hidden', text: ' (내 버전의 줄)' }) : null,
    ])));
  }

  function renderDetail() {
    const observation = value.observations.find(item => item.observation_id === chosen) ?? value.observations[0];
    if (!observation) {
      detail.replaceChildren();
      return;
    }
    const parts = differenceParts(observation, texts);
    const nodes = [el(document, 'h4', { text: `고른 차이: ${parts.label ?? String(observation.description)}` }),
      el(document, 'p', { className: 'difference-description', text: String(observation.description) })];
    if (parts.kind === 'none') {
      nodes.push(el(document, 'p', { className: 'difference-note', text: parts.reason }));
    } else {
      nodes.push(el(document, 'div', { className: 'difference-parts' }, [
        el(document, 'figure', { className: 'difference-part' }, [
          el(document, 'figcaption', { text: '원본 부분' }),
          parts.original.length ? lineList(parts.original, 'difference-original') : el(document, 'p', { text: '(원본에는 없는 줄)' })]),
        el(document, 'figure', { className: 'difference-part difference-part-mine' }, [
          el(document, 'figcaption', { text: '내 버전 부분' }),
          parts.mine.length ? lineList(parts.mine, 'difference-mine') : el(document, 'p', { text: '(내 버전에서 지운 줄)' })]),
      ]), el(document, 'details', { className: 'difference-context', attrs: { open: true } }, [
        el(document, 'summary', { text: `주변 문맥 (앞뒤 ${CONTEXT_LINES}줄)` }), lineList(parts.context, 'difference-unified')]));
      nodes.push(el(document, 'p', { className: 'difference-note', text: MESSAGES.alignment }));
    }
    detail.replaceChildren(...nodes);
    for (const button of observed.querySelectorAll?.('button[data-observation]') ?? []) {
      button.setAttribute('aria-pressed', button.getAttribute('data-observation') === observation.observation_id ? 'true' : 'false');
    }
  }

  function renderObserved() {
    const list = el(document, 'ol', { className: 'difference-list' }, value.observations.map(item => {
      const button = el(document, 'button', { className: 'difference-pick', text: String(item.description),
        attrs: { type: 'button', 'data-observation': item.observation_id, 'aria-pressed': 'false' } });
      button.addEventListener('click', () => { chosen = item.observation_id; renderDetail(); });
      return el(document, 'li', {}, [button]);
    }));
    observed.replaceChildren(el(document, 'h4', { text: `관측된 차이 ${value.observations.length}개` }), list,
      ...value.uncertainties.map(text => el(document, 'p', { className: 'difference-uncertainty', text: String(text) })));
  }

  function renderSegment(segment) {
    const nodes = [el(document, 'h4', { text: '관련 실행 구간' })];
    if (!segment) {
      segmentBox.replaceChildren(...nodes, el(document, 'p', { text: MESSAGES.noSegment }));
      return;
    }
    const which = segment.attemptNo ? `수행 ${segment.visitNo} · 시도 ${segment.attemptNo}${segment.attempts > 1 ? ` (시도 ${segment.attempts}회 중)` : ''}`
      : `수행 ${segment.visitNo} · 시도 기록 없음(실행기가 직접 처리)`;
    const inputs = segment.inputs.length
      ? segment.inputs.map(item => `앞 단계 “${item.responsibility}”(${item.nodeId})${item.attemptNo ? ` 시도 ${item.attemptNo}` : ''}`
        + (item.roles.length ? ` — ${item.roles.join(', ')}` : ''))
      : ['앞 단계에서 받은 것 없음(시작 단계)'];
    const calls = [
      ...segment.models.map(item => `모델 호출${item.label ? ` (${item.label})` : ''} · ${item.tokens} · ${item.state}`),
      ...segment.tools.map(item => `도구 ${item.toolId} · 시도 ${item.attemptNo} · ${item.state}`),
    ];
    const go = el(document, 'button', { className: 'btn btn-quiet', text: '과정에서 이 단계 보기', attrs: { type: 'button' } });
    go.addEventListener('click', () => {
      if (typeof onSelectStep === 'function') onSelectStep({ nodeId: segment.nodeId, visitNo: segment.visitNo, attemptNo: segment.attemptNo });
    });
    go.hidden = typeof onSelectStep !== 'function';
    segmentBox.replaceChildren(...nodes,
      el(document, 'p', { className: 'difference-step' }, [
        el(document, 'strong', { text: `“${segment.responsibility}”` }),
        el(document, 'span', { text: ` (${segment.nodeId}) · ${which}` })]),
      el(document, 'dl', { className: 'kv-list' }, [
        el(document, 'dt', { text: '받은 입력' }),
        el(document, 'dd', {}, [el(document, 'ul', { className: 'plain-list' }, inputs.map(text => el(document, 'li', { text })))]),
        el(document, 'dt', { text: '도구·모델 호출' }),
        el(document, 'dd', {}, [calls.length ? el(document, 'ul', { className: 'plain-list' }, calls.map(text => el(document, 'li', { text })))
          : el(document, 'span', { text: '이 단계의 호출 기록 없음' })]),
        ...(segment.error ? [el(document, 'dt', { text: '오류' }), el(document, 'dd', { text: segment.error })] : []),
      ]),
      el(document, 'p', {}, [go]));
  }

  // `texts` ({ format, original, mine }) are the two exact contents the editor froze, when it
  // had them; `segment` the step the artifact came from (run-detail.mjs segment)
  async function show({ runId, artifactId, alternativeId, title = null, texts: given = null, segment = null } = {}) {
    const route = differenceRoute(basePath, runId, artifactId, alternativeId);
    const mine = ++generation;
    heading.textContent = title ? `차이 살펴보기 — ${title}` : '차이 살펴보기';
    texts = given;
    chosen = null;
    value = null;
    scope.textContent = '';
    observed.replaceChildren();
    detail.replaceChildren();
    renderSegment(segment);
    say(MESSAGES.observing, 'observing');
    try {
      let read;
      try {
        read = await request(route, {});
      } catch (error) {
        if (error?.code !== 'not_found') throw error;
        read = await request(route, { method: 'POST', body: {} });  // observe once, then read
      }
      if (mine !== generation) return null;
      value = read;
      scope.textContent = scopeText(value);
      renderObserved();
      renderDetail();
      say(MESSAGES.observed, 'observed');
      await inquiry.showValue(value);
      return value;
    } catch (error) {
      if (mine === generation) {
        const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
        say(ERROR_MESSAGES[code], code);
      }
      throw error;
    }
  }

  return Object.freeze({ show, get value() { return value; }, inquiry });
}
