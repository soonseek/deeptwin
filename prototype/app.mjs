import { ROLES } from './data.mjs';
import { loadState, saveState, resetState, transition, roleFor, currentDraft } from './state.mjs';
import { renderShell } from './scenes.mjs';
import { detail } from './views.mjs';

const root = document.querySelector('#app');
const dialog = document.querySelector('#detail-dialog');
const detailBody = document.querySelector('#detail-body');
const closeButton = document.querySelector('#detail-close');
let storage;
try { storage = window.sessionStorage; } catch { storage = null; }
let result = loadState(storage);
let state = result.state;
let storageResult = { ok: result.ok, message: result.message };
let storageReadFailed = !result.ok;
let lastDetailTrigger = null;
let candidateRange = null;

function showStorage() {
  const status = document.querySelector('#storage-status');
  status.textContent = storageResult.message;
  status.classList.toggle('warning', !storageResult.ok);
}
function persist() {
  storageResult = saveState(storage, state, { readFailed: storageReadFailed });
  showStorage();
}
function render(focusSelector = null) {
  root.innerHTML = renderShell(state);
  candidateRange = null;
  showStorage();
  if (focusSelector) document.querySelector(focusSelector)?.focus();
}
function change(action, focusSelector = '#scene-title') {
  state = transition(state, action);
  render(focusSelector);
  persist();
}
function openDetail(id, trigger) {
  lastDetailTrigger = trigger;
  detailBody.innerHTML = detail(state, id);
  dialog.showModal();
  closeButton.focus();
}
closeButton.addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => {
  lastDetailTrigger?.focus({ preventScroll: true });
  lastDetailTrigger = null;
});

// Only ranges within real artifact paragraphs are accepted. Paragraph action
// buttons are siblings and never count toward the canonical text offsets.
function captureSelection() {
  candidateRange = null;
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return;
  const range = selection.getRangeAt(0);
  const container = document.querySelector('#original-text');
  if (!container || !container.contains(range.startContainer) || !container.contains(range.endContainer)) return;
  const paragraphFor = node => (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement)?.closest('p[data-start]');
  const first = paragraphFor(range.startContainer);
  const last = paragraphFor(range.endContainer);
  if (!first || !last || !container.contains(first) || !container.contains(last)) return;
  const offset = (paragraph, node, nodeOffset) => {
    const prefix = document.createRange();
    prefix.selectNodeContents(paragraph);
    prefix.setEnd(node, nodeOffset);
    return Number(paragraph.dataset.start) + prefix.toString().length;
  };
  const start = offset(first, range.startContainer, range.startOffset);
  const end = offset(last, range.endContainer, range.endOffset);
  if (start < end) candidateRange = { start, end, role: state.role };
}
document.addEventListener('selectionchange', captureSelection);
root.addEventListener('pointerup', captureSelection);
root.addEventListener('keyup', captureSelection);
root.addEventListener('pointerdown', event => {
  if (event.target.closest('#select-range')) {
    captureSelection();
    event.preventDefault();
  }
});

root.addEventListener('input', event => {
  const element = event.target;
  if (!(element instanceof HTMLTextAreaElement)) return;
  if (element.id === 'own-draft') state = transition(state, { type: 'draft', text: element.value });
  else if (element.id === 'conversation-draft') state = transition(state, { type: 'conversation', text: element.value });
  else if (element.dataset.field) state = transition(state, { type: 'field', name: element.dataset.field, text: element.value });
  else return;
  persist();
  // Do not replace a composing/focused textarea on each keystroke (Korean IME).
  if (element.id === 'own-draft') {
    const draft = currentDraft(state);
    document.querySelector('#draft-state').textContent = draft.text.trim()
      ? `사용자 작성 초안 · 편집 ${draft.revision}회 · 제출/비교 증거 미확정`
      : '사용자 대안 없음 · 초안이 비어 있습니다.';
  }
});
root.addEventListener('change', event => {
  const element = event.target;
  if (!(element instanceof HTMLInputElement)) return;
  if (element.dataset.record) change({ type: 'record', value: element.dataset.record, checked: element.checked }, `[data-record="${element.dataset.record}"]`);
  if (element.id === 'redact') change({ type: 'redact', value: element.checked }, '#redact');
});
root.addEventListener('click', event => {
  const target = event.target.closest('button');
  if (!target || target.disabled) return;
  if (target.dataset.detail) return openDetail(target.dataset.detail, target);
  if (target.dataset.scene) return change({ type: 'scene', value: target.dataset.scene });
  if (target.dataset.mode) return change({ type: 'mode', value: target.dataset.mode }, `[data-mode="${target.dataset.mode}"]`);
  if (target.dataset.role) return change({ type: 'role', value: target.dataset.role }, '.role-picker [aria-pressed="true"]');
  if (target.dataset.design) return change({ type: 'design', value: target.dataset.design }, `[data-design="${target.dataset.design}"]`);
  if (target.dataset.round) return change({ type: 'round', value: target.dataset.round }, `[data-round="${target.dataset.round}"]`);
  if (target.dataset.exploration) {
    state = transition(state, { type: 'exploration', value: target.dataset.exploration });
    return change({ type: 'scene', value: 'V05' });
  }
  if (target.hasAttribute('data-return')) return change({ type: 'return' });
  if (target.dataset.scope) {
    const [start, end] = target.dataset.scope.split(':').map(Number);
    return change({ type: 'selection', start, end }, `[data-scope="${target.dataset.scope}"]`);
  }
  if (target.dataset.paragraph !== undefined) {
    const index = Number(target.dataset.paragraph);
    const paragraphs = roleFor(state).paragraphs;
    if (!Number.isInteger(index) || index < 0 || index >= paragraphs.length) return;
    const start = paragraphs.slice(0, index).reduce((length, paragraph) => length + paragraph.length + 2, 0);
    return change({ type: 'selection', start, end: start + paragraphs[index].length }, `[data-paragraph="${index}"]`);
  }
  if (target.id === 'select-whole') return change({ type: 'selection', start: 0, end: roleFor(state).text.length }, '#select-whole');
  if (target.id === 'select-range') {
    captureSelection();
    if (!candidateRange || candidateRange.role !== state.role) {
      document.querySelector('#selection-feedback').textContent = '원문 문구를 먼저 선택하세요. 키보드로 문단 선택 버튼을 사용할 수도 있습니다.';
      return;
    }
    return change({ type: 'selection', start: candidateRange.start, end: candidateRange.end }, '#select-range');
  }
  if (target.id === 'storage-retry') {
    if (storageReadFailed) {
      if (!window.confirm('이전 탭 보관본을 읽거나 복원하지 못했습니다. 현재 화면의 작성 내용으로 이전 보관본을 덮어쓸까요?')) return;
      storageReadFailed = false;
    }
    return persist();
  }
  if (target.id === 'reset-prototype') {
    if (!window.confirm('이 시제품의 업무 설명·내 버전·대화 메모·화면 선택을 이 탭에서 초기화할까요?')) return;
    const reset = resetState(storage);
    storageResult = reset;
    if (reset.ok) {
      storageReadFailed = false;
      state = reset.state;
      render('#scene-title');
    } else showStorage();
  }
});
render();
