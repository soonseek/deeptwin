import { ARTIFACTS, CASE, ROUNDS, RUNS } from './fixtures.mjs';
import { context, createState, draftKey, load, noteKey, reset, save, transition } from './state.mjs';
import { artifact } from './primitives.mjs';
import { overlay, render, sampleInspection } from './workspace.mjs';

const root = document.querySelector('#app');
const dialog = document.querySelector('#detail-dialog');
const dialogBody = document.querySelector('#detail-body');
const permanentClose = document.querySelector('#detail-close');
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const FILE_EXTENSIONS = new Set(['pdf', 'png', 'jpg', 'jpeg', 'svg', 'csv', 'md', 'txt']);
const DIRECT_ACTIONS = new Set(['area', 'mode', 'run', 'attempt', 'node', 'artifact', 'design', 'focus', 'round', 'difference']);
const scrollPositions = new Map();
const expandedRunGraphs = new Map();
const expandedDetails = new Map();
const attachments = new Map();
let detail = null;
let detailTrigger = null;
let pendingTextScope = null;
let fileMessage = '';

let storage;
try {
  storage = window.sessionStorage;
} catch {
  storage = {
    getItem() { throw new Error('session storage unavailable'); },
    setItem() { throw new Error('session storage unavailable'); },
    removeItem() { throw new Error('session storage unavailable'); },
  };
}
const restored = load(storage);
let state = restored.state;
let blocked = restored.blocked;
let status = restored.message;

const currentRound = () => ROUNDS.find(round => round.id === state.round);
const origin = Object.values(RUNS).find(run => run.attempts.some(attempt => attempt.outputs.includes(CASE.original)));

function revokeAttachment(entry) {
  if (entry?.url) URL.revokeObjectURL(entry.url);
}

function clearAttachments() {
  for (const entry of attachments.values()) revokeAttachment(entry);
  attachments.clear();
}

function rememberView() {
  for (const scroller of root.querySelectorAll('.graph-scroll[data-graph-id]')) {
    scrollPositions.set(scroller.dataset.graphId, scroller.scrollLeft);
  }
  const graphDetails = root.querySelector('details.run-graph');
  const runId = root.querySelector('.run-workbench')?.dataset.run;
  if (graphDetails && runId) expandedRunGraphs.set(runId, graphDetails.open);
  for (const item of root.querySelectorAll('details:not(.run-picker):not(.run-graph)')) {
    expandedDetails.set(detailsKey(item), item.open);
  }
}

function detailsKey(item) {
  const shell = item.closest('.shell');
  const contextId = item.closest('[data-inspected-attempt]')?.dataset.inspectedAttempt
    ?? item.closest('[data-artifact]')?.dataset.artifact
    ?? item.closest('[data-run]')?.dataset.run
    ?? '';
  return JSON.stringify([
    shell?.dataset.area ?? '', shell?.dataset.mode ?? '', item.className,
    item.querySelector(':scope > summary')?.textContent ?? '', contextId,
  ]);
}

function focusedIdentity() {
  const active = document.activeElement;
  if (!active || (!root.contains(active) && !dialog.contains(active))) return null;
  if (active.dataset?.action) return { action: active.dataset.action, value: active.dataset.value ?? '' };
  if (active.dataset?.record) return { record: active.dataset.record };
  return active.id ? { id: active.id } : null;
}

function findIdentity(identity, container = document) {
  if (!identity) return null;
  if (identity.id) return container.querySelector(`#${CSS.escape(identity.id)}`);
  if (identity.record) return [...container.querySelectorAll('[data-record]')]
    .find(item => item.dataset.record === identity.record) ?? null;
  return [...container.querySelectorAll('[data-action]')]
    .find(item => item.dataset.action === identity.action && (item.dataset.value ?? '') === identity.value) ?? null;
}

function updateStatus() {
  const output = root.querySelector('#storage-status');
  if (output) output.textContent = status;
}

function updateDraftStatus() {
  const output = root.querySelector('#draft-status');
  if (!output || !context(state).artifact) return;
  const key = draftKey(state);
  const present = (state.drafts[key] ?? '').length > 0 || attachments.has(key);
  output.textContent = present
    ? '이 정확한 맥락에 자기 버전이 있습니다.'
    : '이 정확한 맥락에는 아직 자기 버전이 없습니다.';
}

function updateFileStatus(message = fileMessage) {
  const output = root.querySelector('#file-status');
  if (!output || !context(state).artifact) return;
  output.replaceChildren();
  const entry = attachments.get(draftKey(state));
  const prefix = message || (entry
    ? '첨부 파일 · 이 탭 메모리에만 유지: '
    : '첨부 파일은 복원되지 않음 · 새 파일은 이 탭 메모리에만 유지됩니다.');
  output.append(document.createTextNode(prefix));
  if (!entry) return;
  const name = document.createElement('span');
  name.className = 'file-name';
  name.textContent = entry.file.name;
  output.append(name, document.createTextNode(' · '));
  const download = document.createElement('a');
  download.href = entry.url;
  download.download = entry.file.name;
  download.textContent = '실제 첨부 파일 받기';
  output.append(download);
  const clear = document.createElement('button');
  clear.type = 'button';
  clear.dataset.action = 'clearFile';
  clear.dataset.value = '';
  clear.textContent = '첨부 지우기';
  output.append(clear);
  if (entry.raster) {
    const image = document.createElement('img');
    image.className = 'local-raster-preview';
    image.alt = `${entry.file.name} 로컬 미리보기`;
    image.src = entry.url;
    image.addEventListener('error', () => image.remove(), { once: true });
    output.append(image);
  }
}

function updateFreshAttachment() {
  const output = root.querySelector('.fresh-growth h3 + blockquote');
  if (!output || !context(state).artifact) return;
  const key = draftKey(state);
  const draft = state.drafts[key] ?? '';
  output.textContent = draft || '현재 맥락에 작성된 자기 버전 없음';
  root.querySelector('.fresh-growth .local-file-context')?.remove();
  const entry = attachments.get(key);
  if (!entry) return;
  const file = document.createElement('p');
  file.className = 'local-file-context';
  file.textContent = `로컬 첨부 파일 있음 · ${entry.file.name} · 이 탭 메모리에만 유지 · 분석되지 않음`;
  output.after(file);
}

function restoreView(identity, ensureSelected) {
  for (const scroller of root.querySelectorAll('.graph-scroll[data-graph-id]')) {
    if (scrollPositions.has(scroller.dataset.graphId)) scroller.scrollLeft = scrollPositions.get(scroller.dataset.graphId);
  }
  const graphDetails = root.querySelector('details.run-graph');
  const runId = root.querySelector('.run-workbench')?.dataset.run;
  if (graphDetails && runId) {
    if (state.mode === 'graph') graphDetails.open = true;
    else if (expandedRunGraphs.has(runId)) graphDetails.open = expandedRunGraphs.get(runId);
  }
  for (const item of root.querySelectorAll('details:not(.run-picker):not(.run-graph)')) {
    if (expandedDetails.has(detailsKey(item))) item.open = expandedDetails.get(detailsKey(item));
  }
  if (ensureSelected) {
    const selected = root.querySelector('.run-graph .node.selected');
    const scroller = selected?.closest('.graph-scroll');
    if (selected && scroller) {
      const box = selected.getBoundingClientRect();
      const frame = scroller.getBoundingClientRect();
      if (box.left < frame.left) scroller.scrollLeft -= frame.left - box.left + 20;
      else if (box.right > frame.right) scroller.scrollLeft += box.right - frame.right + 20;
    }
  }
  if (identity) {
    const matched = findIdentity(identity, root);
    const target = matched?.getClientRects().length ? matched : root.querySelector('#page-title');
    target?.focus({ preventScroll: true });
  }
}

function paint({ restoreFocus = true, ensureSelected = false } = {}) {
  const identity = restoreFocus ? focusedIdentity() : null;
  rememberView();
  root.innerHTML = render(state);
  restoreTextareasFromState();
  updateStatus();
  updateFileStatus();
  updateDraftStatus();
  updateFreshAttachment();
  getSelection()?.removeAllRanges();
  restoreView(identity, ensureSelected);
}

function restoreTextareasFromState() {
  for (const textarea of root.querySelectorAll('textarea[data-field]')) {
    const field = textarea.dataset.field;
    if (field === 'draft') textarea.value = context(state).artifact ? state.drafts[draftKey(state)] ?? '' : '';
    else if (field === 'note') textarea.value = state.notes[noteKey(state)] ?? '';
    else if (field === 'workText') textarea.value = state.workText;
    else if (field === 'designText') textarea.value = state.designText;
  }
}

function persist() {
  const result = save(storage, state, blocked);
  status = result.message;
  updateStatus();
  return result;
}

function captureRange() {
  const body = root.querySelector('#original-body');
  const selection = getSelection();
  if (!body || !selection || selection.rangeCount !== 1 || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  if (!body.contains(range.startContainer) || !body.contains(range.endContainer)) return null;
  const beforeStart = document.createRange();
  beforeStart.selectNodeContents(body);
  beforeStart.setEnd(range.startContainer, range.startOffset);
  const beforeEnd = document.createRange();
  beforeEnd.selectNodeContents(body);
  beforeEnd.setEnd(range.endContainer, range.endOffset);
  return {
    artifact: context(state).artifact,
    key: draftKey(state),
    start: beforeStart.toString().length,
    end: beforeEnd.toString().length,
  };
}

function dialogMarkup() {
  if (!detail) return '';
  if (detail.kind === 'normal') return overlay(state, state.overlay);
  if (detail.kind === 'sample') return sampleInspection(detail.node, detail.attempt);
  if (detail.kind === 'evidence') return `<div class="overlay-content"><h2 id="detail-heading">고정 합성 사례의 근거 파일</h2><p>사전 구성된 합성 자료 · 현재 입력과 별개</p>${artifact(detail.artifact)}<button type="button" data-action="close" data-value="">닫기</button></div>`;
  return '';
}

function renderDialog(focusIdentity = null) {
  dialogBody.innerHTML = dialogMarkup();
  const heading = dialogBody.querySelector('h2');
  if (heading) heading.id = 'detail-heading';
  (findIdentity(focusIdentity, dialogBody) ?? permanentClose).focus({ preventScroll: true });
}

function openDetail(next, trigger) {
  detail = next;
  detailTrigger = trigger instanceof HTMLElement ? trigger : document.activeElement;
  renderDialog();
  if (!dialog.open) dialog.showModal();
  permanentClose.focus({ preventScroll: true });
}

function closeDetail() {
  if (detail?.kind === 'normal' && state.overlay !== null) {
    state = transition(state, { type: 'close' });
    persist();
  }
  detail = null;
  if (dialog.open) dialog.close();
  dialogBody.replaceChildren();
  const target = detailTrigger?.isConnected ? detailTrigger : root.querySelector('#page-title');
  detailTrigger = null;
  target?.focus({ preventScroll: true });
}

function updateDialogState(action) {
  const focus = focusedIdentity();
  state = transition(state, action);
  persist();
  renderDialog(focus);
}

function handleFile(input) {
  const file = input.files?.[0];
  input.value = '';
  if (!file || !context(state).artifact) return;
  const extension = file.name.split('.').at(-1)?.toLowerCase() ?? '';
  const current = attachments.get(draftKey(state));
  if (!FILE_EXTENSIONS.has(extension) || file.size > MAX_FILE_BYTES) {
    fileMessage = '첨부 실패 · 5MiB 이하의 PDF/PNG/JPG/JPEG/SVG/CSV/MD/TXT 형식만 가능 · 이전 파일 유지: ';
    updateFileStatus();
    return;
  }
  revokeAttachment(current);
  const raster = extension === 'png' || extension === 'jpg' || extension === 'jpeg';
  attachments.set(draftKey(state), { file, url: URL.createObjectURL(file), raster });
  fileMessage = '첨부 파일 · 이 탭 메모리에만 유지: ';
  state = transition(state, { type: 'sample', value: false });
  persist();
  updateFileStatus();
  updateDraftStatus();
}

function rootTransition(action, { ensureSelected = false } = {}) {
  state = transition(state, action);
  persist();
  fileMessage = '';
  paint({ ensureSelected });
}

function pairChoice(side, nodeId) {
  const round = currentRound();
  const run = RUNS[side === 'baseline' ? round.baselineRun : round.candidateRun];
  const attempt = run.attempts.filter(item => item.node === nodeId).at(-1);
  return attempt?.id ?? `@${nodeId}`;
}

function activate(target) {
  const type = target.dataset.action;
  const value = target.dataset.value ?? '';
  if (DIRECT_ACTIONS.has(type)) {
    rootTransition({ type, value }, { ensureSelected: type === 'attempt' || type === 'node' });
  } else if (type === 'scope') {
    rootTransition({ type: 'scope', value: value === 'whole' ? { kind: 'whole' } : { kind: 'region', id: value } });
  } else if (type === 'textScope') {
    const captured = pendingTextScope ?? captureRange();
    pendingTextScope = null;
    if (captured && captured.artifact === context(state).artifact && captured.key === draftKey(state)) {
      rootTransition({ type: 'scope', value: { kind: 'text', start: captured.start, end: captured.end } });
    }
  } else if (type === 'consumer') {
    const receiver = RUNS[state.run].attempts.find(attempt => attempt.id === value);
    if (receiver) rootTransition({ type: 'attempt', run: state.run, value: receiver.id }, { ensureSelected: true });
  } else if (type === 'designNode') {
    rootTransition({ type: 'design', value: value.split(':')[0] });
  } else if (type === 'pairNode') {
    const [side, nodeId] = value.split(':');
    rootTransition({ type: 'pair', side, value: pairChoice(side, nodeId) }, { ensureSelected: true });
  } else if (type === 'pairAttempt') {
    const [side, ...parts] = value.split(':');
    rootTransition({ type: 'pair', side, value: parts.join(':') }, { ensureSelected: true });
  } else if (type === 'currentGrowth') {
    state = transition(state, { type: 'sample', value: false });
    rootTransition({ type: 'area', value: 'growth' });
  } else if (type === 'sample') {
    rootTransition({ type: 'sample', value: value === 'true' });
  } else if (type === 'overlay') {
    state = transition(state, { type: 'overlay', value });
    persist();
    openDetail({ kind: 'normal' }, target);
  } else if (type === 'sampleNode') {
    openDetail({ kind: 'sample', node: value, attempt: undefined }, target);
  } else if (type === 'sampleAttempt' || type === 'sampleConsumer') {
    const current = origin.attempts.find(item => item.id === detail?.attempt)
      ?? origin.attempts.filter(item => item.node === detail?.node).at(-1);
    const allowed = type === 'sampleAttempt'
      ? origin.attempts.filter(item => item.node === detail?.node).map(item => item.id)
      : current?.consumers.map(item => item.attempt) ?? [];
    const attempt = allowed.includes(value) ? origin.attempts.find(item => item.id === value) : null;
    if (detail?.kind === 'sample' && attempt) {
      const focus = focusedIdentity();
      detail = { kind: 'sample', node: attempt.node, attempt: attempt.id };
      renderDialog(focus);
    }
  } else if (type === 'evidence') {
    if (Object.hasOwn(ARTIFACTS, value)) openDetail({ kind: 'evidence', artifact: value }, target);
  } else if (type === 'close') {
    closeDetail();
  } else if (type === 'clearFile') {
    const key = context(state).artifact ? draftKey(state) : null;
    if (!key || !attachments.has(key)) return;
    revokeAttachment(attachments.get(key));
    attachments.delete(key);
    fileMessage = '첨부 파일 지움 · 파일 바이트는 보관되지 않음';
    updateFileStatus();
    updateDraftStatus();
  } else if (type === 'save') {
    if (blocked && !confirm('읽지 못한 기존 보관본을 현재 메모리 내용으로 바꿀까요?')) return;
    const result = save(storage, state, false);
    status = result.message;
    if (result.ok) blocked = false;
    updateStatus();
  } else if (type === 'reset') {
    if (!confirm('이 탭의 시험용 작성 내용과 첨부 파일을 초기화할까요?')) return;
    const result = reset(storage);
    if (!result.ok) {
      status = result.message;
      updateStatus();
      return;
    }
    clearAttachments();
    state = createState();
    blocked = false;
    status = '시험용 작성 내용 초기화 완료 · 다른 보관 값은 유지';
    fileMessage = '';
    paint();
  }
}

root.addEventListener('pointerdown', event => {
  const target = event.target.closest('[data-action="textScope"]');
  if (!target) return;
  pendingTextScope = captureRange();
  event.preventDefault();
});

root.addEventListener('click', event => {
  const target = event.target.closest('[data-action]');
  if (target) activate(target);
});

root.addEventListener('keydown', event => {
  const target = event.target.closest('g[role="button"][data-action]');
  if (!target || !['Enter', ' '].includes(event.key)) return;
  event.preventDefault();
  activate(target);
});

root.addEventListener('input', event => {
  const field = event.target.dataset?.field;
  if (!field) return;
  state = transition(state, { type: field, value: event.target.value });
  persist();
  if (field === 'draft') updateDraftStatus();
});

root.addEventListener('change', event => {
  if (event.target.id === 'alternative-file') handleFile(event.target);
});

dialog.addEventListener('click', event => {
  const target = event.target.closest('[data-action]');
  if (target) activate(target);
});
dialog.addEventListener('change', event => {
  if (detail?.kind !== 'normal' || state.overlay !== 'logs') return;
  if (event.target.id === 'redact') updateDialogState({ type: 'redact', value: event.target.checked });
  else if (event.target.dataset.record) updateDialogState({ type: 'record', value: event.target.dataset.record });
});
dialog.addEventListener('cancel', event => {
  event.preventDefault();
  closeDetail();
});
permanentClose.addEventListener('click', closeDetail);

window.addEventListener('pagehide', clearAttachments);
window.addEventListener('pageshow', event => {
  if (event.persisted) {
    fileMessage = '첨부 파일은 복원되지 않음 · 새 파일은 이 탭 메모리에만 유지됩니다.';
    updateFileStatus();
    updateDraftStatus();
    updateFreshAttachment();
  }
});

paint({ restoreFocus: false });
if (state.overlay) openDetail({ kind: 'normal' }, root.querySelector('#page-title'));
