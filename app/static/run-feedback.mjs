// UI phase 4 (docs/ui/2026-09-26-product-ux-redesign.md §5.3, §6): the owner's process feedback
// on a run — an optional mark (괜찮음 / 확인 필요) and an optional memo, on the run as a whole or
// on one node's exact visit and attempt (GET|POST {base}api/v1/runs/{run}/feedback,
// run-feedback-v1). No reason is ever asked for: a mark alone, a memo alone or both are each a
// complete feedback (FR-016). Feedback is not an alternative ("내 버전") and is never counted as
// one (UX-AC05). Saving is explicit; a change or a clear is a new revision over the exact one it
// was made from, so a stale screen is refused and never silently wins.
//
// The pure half (routes, commands, the lookup by target, the header summary, the graph and
// timeline markers) and the DOM half (`createFeedbackControl`: two toggle buttons with
// aria-pressed, an optional memo, an explicit save, a clear and a saved state) live here. All
// text reaches the DOM through textContent.
//
// UI phase 5: every revision stays on the server (`history`); the control shows a small "이전 기록
// N건" disclosure — N from the target's own revision number — that reads the earlier revisions
// (mark, memo, time; a clear says so) only when the owner opens it.

import { FEEDBACK_MARK_LABELS, FEEDBACK_MARK_TONES, relativeTime, absoluteTime } from './ui-format.mjs';
import { el, timeStamp } from './ui-parts.mjs';

export const FEEDBACK_SCHEMA = 'process-feedback-command-v1';
export const LIST_SCHEMA = 'process-feedback-list-v1';
export const MARKS = Object.freeze(['ok', 'needs_attention']);
export const MEMO_MAX = 4000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
const NODE_ID = /^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$/;

export const MESSAGES = Object.freeze({
  hint: '이유를 적지 않아도 됩니다. 표시만, 메모만, 또는 둘 다 남길 수 있습니다.',
  notAlternative: '피드백은 내 버전(대안)이 아니며 대안으로 세지 않습니다.',
  memoLabel: `메모 (선택, 최대 ${MEMO_MAX.toLocaleString('ko-KR')}자)`,
  none: '아직 남긴 피드백이 없습니다.',
  dirty: '저장하지 않은 변경이 있습니다.',
  empty: '표시를 고르거나 메모를 쓰면 저장할 수 있습니다.',
  emptySaved: '표시와 메모를 모두 비우려면 "지우기"를 누르세요.',
  saving: '저장하는 중…',
  clearing: '지우는 중…',
  cleared: '피드백을 지웠습니다. 이전 기록은 남아 있습니다.',
  tooLong: `메모는 ${MEMO_MAX.toLocaleString('ko-KR')}자까지 쓸 수 있습니다.`,
});

export const ERROR_MESSAGES = Object.freeze({
  conflict: '다른 화면에서 이 피드백을 먼저 바꿨습니다. 최신 내용을 불러왔습니다.',
  not_found: '이 실행이나 단계를 찾지 못해 저장하지 않았습니다.',
  too_large: `메모는 ${MEMO_MAX.toLocaleString('ko-KR')}자까지 쓸 수 있습니다.`,
  invalid_input: '저장할 수 없는 내용입니다.',
  unauthenticated: '브라우저 세션이 없습니다. 다시 로그인해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다. 화면을 새로고침한 뒤 다시 시도해 주세요.',
  unavailable: '저장하지 못했습니다. 잠시 후 다시 시도해 주세요.',
});

function fail(message, code = 'invalid_input') {
  throw Object.assign(new Error(message), { code });
}

export function feedbackRoute(basePath, runId) {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  if (typeof runId !== 'string' || !UUID.test(runId)) fail('run id is not a canonical UUID');
  return `${basePath.slice(0, -1)}/api/v1/runs/${runId}/feedback`;
}

// the exact target: the run, or one node's visit and attempt (null when the visit has none)
export function runTarget() {
  return Object.freeze({ scope: 'run' });
}

export function stepTarget(nodeId, visitNo, attemptNo = null) {
  if (typeof nodeId !== 'string' || !NODE_ID.test(nodeId)) fail('node id is malformed');
  if (!Number.isSafeInteger(visitNo) || visitNo < 1) fail('visit number is malformed');
  if (attemptNo !== null && (!Number.isSafeInteger(attemptNo) || attemptNo < 1)) fail('attempt number is malformed');
  return Object.freeze({ scope: 'step', node_id: nodeId, visit_no: visitNo, attempt_no: attemptNo });
}

export function targetKey(target) {
  if (target?.scope === 'run') return 'run';
  if (target?.scope !== 'step') fail('target is malformed');
  return `step:${target.node_id}:${target.visit_no}:${target.attempt_no ?? '-'}`;
}

// a typed memo as the server takes it: blank is no memo
export function memoValue(text) {
  const value = typeof text === 'string' ? text : '';
  return value.trim() ? value : null;
}

// the exact command body; a set carries a mark or a memo, a clear neither
export function feedbackCommand({ commandId, target, expectedRevision = 0, action = 'set', mark = null, memo = null } = {}) {
  if (typeof commandId !== 'string' || !UUID.test(commandId)) fail('command id is not a canonical UUID');
  if (!['set', 'clear'].includes(action)) fail('action is unknown');
  if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 0) fail('expected revision is malformed');
  targetKey(target);
  if (mark !== null && !MARKS.includes(mark)) fail('mark is unknown');
  const text = memo === null ? null : memoValue(memo);
  if (text !== null && [...text].length > MEMO_MAX) fail('memo is too long', 'too_large');
  if (action === 'set' && mark === null && text === null) fail('a feedback needs a mark or a memo');
  if (action === 'clear' && (mark !== null || text !== null)) fail('a clear carries nothing');
  return { schema_version: FEEDBACK_SCHEMA, command_id: commandId, action, target: { ...target },
    expected_revision: expectedRevision, mark: action === 'clear' ? null : mark, memo: action === 'clear' ? null : text };
}

// the latest revision of every target (a cleared one included), by target key
export function feedbackIndex(feedback) {
  const index = new Map();
  if (feedback?.run) index.set('run', feedback.run);
  for (const item of Array.isArray(feedback?.steps) ? feedback.steps : []) {
    try { index.set(targetKey(item.target), item); } catch { /* a malformed item is not shown */ }
  }
  return index;
}

// the current feedback of one target (null when there is none or it was cleared) and the
// revision a change must name
export function feedbackFor(index, target) {
  const item = index.get(targetKey(target)) ?? null;
  return Object.freeze({ item: item?.state === 'set' ? item : null, revision: Number.isSafeInteger(item?.revision) ? item.revision : 0 });
}

function markerOf(item) {
  if (item.mark === 'needs_attention') return 'needs_attention';
  if (item.mark === 'ok') return 'ok';
  return 'memo';
}

export const MARKER_TEXT = Object.freeze({
  needs_attention: ['!', '피드백: 확인 필요'], ok: ['✓', '피드백: 괜찮음'], memo: ['✎', '피드백: 메모'],
});

// one marker per node: 확인 필요 over 괜찮음 over a memo alone, across its visits and attempts
export function nodeMarkers(feedback) {
  const rank = { needs_attention: 3, ok: 2, memo: 1 };
  const markers = new Map();
  for (const item of Array.isArray(feedback?.steps) ? feedback.steps : []) {
    if (item?.state !== 'set' || item.target?.scope !== 'step') continue;
    const kind = markerOf(item);
    const known = markers.get(item.target.node_id);
    if (!known || rank[kind] > rank[known.kind]) {
      markers.set(item.target.node_id, Object.freeze({ kind, glyph: MARKER_TEXT[kind][0], label: MARKER_TEXT[kind][1] }));
    }
  }
  return markers;
}

// the marker of one exact visit/attempt (a timeline row), or null
export function stepMarker(index, nodeId, visitNo, attemptNo) {
  const item = index.get(`step:${nodeId}:${visitNo}:${attemptNo ?? '-'}`);
  if (!item || item.state !== 'set') return null;
  const kind = markerOf(item);
  return Object.freeze({ kind, glyph: MARKER_TEXT[kind][0], label: MARKER_TEXT[kind][1] });
}

// the run header's one line: "결과 전체: 확인 필요 · 확인 필요 2개 단계 · 괜찮음 1개 단계"
export function feedbackSummary(feedback) {
  const run = feedback?.run?.state === 'set' ? feedback.run : null;
  const byNode = nodeMarkers(feedback);
  const count = kind => [...byNode.values()].filter(item => item.kind === kind).length;
  // one part per kind, each with its own tone: a 괜찮음 count never reads as a warning
  const parts = [];
  if (run) {
    parts.push(Object.freeze({ label: `결과 전체: ${run.mark ? FEEDBACK_MARK_LABELS[run.mark] : '메모'}`,
      tone: run.mark ? FEEDBACK_MARK_TONES[run.mark] : 'neutral' }));
  }
  const attention = count('needs_attention');
  const ok = count('ok');
  const memo = count('memo');
  if (attention) parts.push(Object.freeze({ label: `확인 필요 ${attention}개 단계`, tone: 'warn' }));
  if (ok) parts.push(Object.freeze({ label: `괜찮음 ${ok}개 단계`, tone: 'ok' }));
  if (memo) parts.push(Object.freeze({ label: `메모만 ${memo}개 단계`, tone: 'neutral' }));
  return Object.freeze({ any: parts.length > 0, parts: Object.freeze(parts), text: parts.map(part => part.label).join(' · '),
    attention, ok, memo, run, tone: run?.mark === 'needs_attention' || attention ? 'warn' : 'ok' });
}

// how many earlier records one target has: every revision before the one shown (a cleared
// target shows none, so all its revisions — the clear included — are earlier records)
export function earlierCount(latest) {
  if (!latest || !Number.isSafeInteger(latest.revision) || latest.revision < 1) return 0;
  return latest.state === 'set' ? latest.revision - 1 : latest.revision;
}

// the earlier revisions of one target from the server's history, newest first
export function earlierRevisions(history, target, latest = null) {
  const key = targetKey(target);
  return (Array.isArray(history) ? history : [])
    .filter(item => { try { return targetKey(item.target) === key; } catch { return false; } })
    .filter(item => !(latest?.state === 'set' && item.revision === latest.revision))
    .sort((a, b) => b.revision - a.revision);
}

export function historyLine(item) {
  if (item.state === 'cleared') return `수정본 ${item.revision} · 지움`;
  const parts = [`수정본 ${item.revision}`];
  parts.push(item.mark ? FEEDBACK_MARK_LABELS[item.mark] ?? item.mark : '표시 없음');
  if (typeof item.memo === 'string' && item.memo) {
    const memo = [...item.memo].length > 80 ? `${[...item.memo].slice(0, 79).join('')}…` : item.memo;
    parts.push(`메모 “${memo}”`);
  }
  return parts.join(' · ');
}

// "저장됨 · 3분 전" (the absolute local time rides as the title)
export function savedText(item, now = Date.now()) {
  if (!item) return '';
  const when = relativeTime(item.recorded_at_utc, now);
  return when ? `저장됨 · ${when}` : '저장됨';
}

// ---- DOM: one target's control --------------------------------------------------------------

// `onSave({ mark, memo })` and `onClear()` resolve once the server recorded the revision (the
// caller re-renders the control through `show`); a refusal rejects with the server's code
export function createFeedbackControl({ document, idPrefix, onSave, onClear, onHistory = null, now = () => Date.now() } = {}) {
  if (typeof document?.createElement !== 'function') fail('a document is required');
  if (typeof idPrefix !== 'string' || !/^[a-z][a-z0-9-]*$/.test(idPrefix)) fail('an id prefix is required');
  if (typeof onSave !== 'function' || typeof onClear !== 'function') fail('save and clear are required');
  const memoId = `${idPrefix}-memo`;
  const title = el(document, 'h4', { className: 'feedback-title' });
  const hint = el(document, 'p', { className: 'feedback-hint', text: MESSAGES.hint });
  const buttons = Object.fromEntries(MARKS.map(mark => {
    const button = el(document, 'button', { className: 'feedback-mark', attrs: { type: 'button', 'data-mark': mark,
      'data-tone': FEEDBACK_MARK_TONES[mark], 'aria-pressed': 'false' } }, [
      el(document, 'span', { className: 'feedback-glyph', text: mark === 'ok' ? '✓' : '!', attrs: { 'aria-hidden': 'true' } }),
      el(document, 'span', { text: FEEDBACK_MARK_LABELS[mark] }),
    ]);
    return [mark, button];
  }));
  const memoToggle = el(document, 'button', { className: 'btn btn-quiet feedback-memo-toggle', text: '메모 쓰기',
    attrs: { type: 'button', 'aria-expanded': 'false', 'aria-controls': memoId } });
  const marks = el(document, 'div', { className: 'feedback-marks', attrs: { role: 'group', 'aria-label': '표시 (선택)' } },
    [buttons.ok, buttons.needs_attention, memoToggle]);
  const area = el(document, 'textarea', { className: 'feedback-memo-text', attrs: { id: memoId, rows: '3',
    maxlength: String(MEMO_MAX) } });
  const counter = el(document, 'p', { className: 'feedback-count', attrs: { 'aria-live': 'off' } });
  const memoBox = el(document, 'div', { className: 'feedback-memo' }, [
    el(document, 'label', { text: MESSAGES.memoLabel, attrs: { for: memoId } }), area, counter]);
  memoBox.hidden = true;
  const save = el(document, 'button', { className: 'btn btn-primary feedback-save', text: '저장', attrs: { type: 'button' } });
  const clear = el(document, 'button', { className: 'btn btn-quiet feedback-clear', text: '지우기', attrs: { type: 'button' } });
  const status = el(document, 'p', { className: 'feedback-status', attrs: { role: 'status', 'aria-live': 'polite' } });
  const actions = el(document, 'div', { className: 'feedback-actions' }, [save, clear, status]);
  const historySummary = el(document, 'summary', { text: '' });
  const historyList = el(document, 'ol', { attrs: { 'aria-label': '이전 피드백 기록' } });
  const history = el(document, 'details', { className: 'feedback-history' }, [historySummary, historyList]);
  history.hidden = true;
  const root = el(document, 'section', { className: 'feedback-box', attrs: { 'data-feedback-for': idPrefix } },
    [el(document, 'div', { className: 'feedback-head' }, [title, hint]), marks, memoBox, actions, history]);
  let latest = null;    // the target's latest revision, set or cleared (for "이전 기록 N건")
  let historyTurn = 0;

  async function readHistory() {
    if (typeof onHistory !== 'function' || !history.open) return;
    const mine = ++historyTurn;
    historyList.replaceChildren(el(document, 'li', { text: '이전 기록을 읽는 중…' }));
    try {
      const items = await onHistory(latest);
      if (mine !== historyTurn) return;
      historyList.replaceChildren(...(items.length ? items.map(item => el(document, 'li', { attrs: { 'data-revision': String(item.revision) } }, [
        el(document, 'span', { text: historyLine(item) }), timeStamp(document, item.recorded_at_utc, { now: now() })]))
        : [el(document, 'li', { text: '이전 기록이 없습니다.' })]));
    } catch {
      if (mine === historyTurn) historyList.replaceChildren(el(document, 'li', { text: '이전 기록을 읽지 못했습니다.' }));
    }
  }
  history.addEventListener('toggle', () => { readHistory(); });

  let saved = null;     // the target's current feedback (null: none or cleared)
  let mark = null;      // the owner's pick on screen
  let busy = false;
  let dirty = false;
  let note = null;      // a one-off message (cleared, a refusal) until the next edit

  function say(text, state, when = null) {
    status.textContent = text;
    status.dataset.state = state;
    if (when) status.setAttribute('title', when); else status.removeAttribute?.('title');
  }

  function refresh() {
    for (const [value, button] of Object.entries(buttons)) button.setAttribute('aria-pressed', mark === value ? 'true' : 'false');
    const text = memoValue(area.value);
    const length = [...String(area.value ?? '')].length;
    counter.textContent = `${length.toLocaleString('ko-KR')} / ${MEMO_MAX.toLocaleString('ko-KR')}자`;
    const complete = mark !== null || text !== null;
    save.disabled = busy || !dirty || !complete || length > MEMO_MAX;
    clear.hidden = saved === null;
    clear.disabled = busy;
    root.dataset.state = saved === null ? 'none' : 'saved';
    if (busy) return;
    if (note) { say(note.text, note.state); return; }
    if (dirty && length > MEMO_MAX) say(MESSAGES.tooLong, 'invalid');
    else if (dirty && !complete) say(saved ? MESSAGES.emptySaved : MESSAGES.empty, 'empty');
    else if (dirty) say(MESSAGES.dirty, 'dirty');
    else if (saved) say(savedText(saved, now()), 'saved', absoluteTime(saved.recorded_at_utc));
    else say(MESSAGES.none, 'none');
  }

  function edited() {
    dirty = true;
    note = null;
    refresh();
  }

  function openMemo(open) {
    memoBox.hidden = !open;
    memoToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    memoToggle.textContent = open ? '메모 접기' : '메모 쓰기';
  }

  for (const [value, button] of Object.entries(buttons)) {
    // a pressed mark pressed again is no mark: the owner can always take a mark back
    button.addEventListener('click', () => { mark = mark === value ? null : value; edited(); });
  }
  memoToggle.addEventListener('click', () => {
    openMemo(memoBox.hidden);
    if (!memoBox.hidden) area.focus?.();
  });
  area.addEventListener('input', edited);

  async function act(run, pending) {
    if (busy) return null;
    busy = true;
    save.disabled = true;
    clear.disabled = true;
    say(pending, 'saving');
    try {
      return await run();
    } catch (error) {
      const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
      note = { text: ERROR_MESSAGES[code], state: code };
      return null;
    } finally {
      busy = false;
      refresh();
    }
  }

  save.addEventListener('click', () => act(async () => {
    const value = await onSave({ mark, memo: memoValue(area.value) });
    note = null;
    return value;
  }, MESSAGES.saving));
  clear.addEventListener('click', () => act(async () => {
    const value = await onClear();
    note = { text: MESSAGES.cleared, state: 'cleared' };
    return value;
  }, MESSAGES.clearing));

  // show one target's current feedback; `keepDraft` keeps an unsaved edit the owner is making
  // (another place of the page saved, and this control's own draft must not be lost)
  function show({ heading, item = null, keepDraft = false, last = null } = {}) {
    title.textContent = heading ?? '';
    root.setAttribute('aria-label', `${heading ?? ''}에 대한 피드백`);
    saved = item ?? null;
    latest = last ?? item ?? null;
    const earlier = typeof onHistory === 'function' ? earlierCount(latest) : 0;
    history.hidden = earlier === 0;
    historySummary.textContent = `이전 기록 ${earlier}건`;
    if (history.open) readHistory();
    if (!(keepDraft && dirty)) {
      note = null;
      mark = saved?.mark ?? null;
      area.value = saved?.memo ?? '';
      dirty = false;
      openMemo(Boolean(saved?.memo));
    }
    refresh();
  }

  refresh();
  return Object.freeze({ root, show, get mark() { return mark; }, get dirty() { return dirty; },
    get saved() { return saved; }, buttons, area, save, clear, status, history });
}
